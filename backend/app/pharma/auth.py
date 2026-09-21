"""Independent, revocable PharmaScope sessions with workspace role checks."""

import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy import select

from .db import now, text_hash, transaction
from .errors import PharmaError, require

PASSWORDS = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(32))
ROLES = {"reader": 0, "analyst": 1, "reviewer": 2, "admin": 3}
COOKIE = "pharma_session"
CSRF_COOKIE = "pharma_csrf"


@dataclass(frozen=True)
class Principal:
    user: dict
    session: dict
    workspace_id: str | None = None
    role: str = "reader"

    @property
    def user_id(self):
        return self.user["id"]

    def require_role(self, role):
        require(ROLES[self.role] >= ROLES[role], "FORBIDDEN", "当前角色无权执行此操作", 403)

    def owns(self, resource, key="created_by"):
        require(resource[key] == self.user_id or ROLES[self.role] >= ROLES["reviewer"])


def origin_check(request):
    origin = request.headers.get("origin")
    allowed = set(filter(None, os.environ.get("PHARMA_ALLOWED_ORIGINS", "").split(",")))
    allowed.add(str(request.base_url).rstrip("/"))
    require(origin is None or origin in allowed, "CSRF_FAILED", "请求来源校验失败", 403)
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise PharmaError("CSRF_FAILED", "不允许跨站请求", 403)


def authenticate(request, workspace_id=None):
    token = request.cookies.get(COOKIE, "")
    with transaction() as repo:
        sessions = repo.rows("app_session", token_hash=text_hash(token)) if token else []
        require(sessions and not sessions[0]["revoked_at"], "AUTH_REQUIRED", "请先登录", 401)
        session = sessions[0]
        from datetime import datetime

        require(datetime.fromisoformat(session["expires_at"]) > now(), "AUTH_REQUIRED", "会话已过期", 401)
        user = repo.get("app_user", session["user_id"])
        require(user["is_active"], "AUTH_REQUIRED", "账户已停用", 401)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin_check(request)
            require(hmac.compare_digest(text_hash(request.headers.get("x-csrf-token", "")), session["csrf_hash"]), "CSRF_FAILED", "安全令牌已过期，请刷新页面", 403)
        role = "reader"
        if workspace_id:
            scoped = type(repo)(repo.connection, workspace_id)
            members = scoped.rows("membership", user_id=user["id"], enabled=True)
            require(members)
            role = members[0]["role"]
        return Principal({k: user[k] for k in ["id", "email", "display_name", "is_active"]}, session, workspace_id, role)


def me(request, principal=None):
    principal = principal or authenticate(request)
    with transaction() as repo:
        member, workspace = repo.table("membership"), repo.table("workspace")
        rows = (
            repo.connection.execute(
                select(member.c.workspace_id, workspace.c.name.label("workspace_name"), member.c.role, workspace.c.settings)
                .join(workspace, member.c.workspace_id == workspace.c.id)
                .where(member.c.user_id == principal.user_id, member.c.enabled.is_(True))
            )
            .mappings()
            .all()
        )
        memberships = [{"workspace_id": str(row["workspace_id"]), "workspace_name": row["workspace_name"], "role": row["role"], "data_mode": row["settings"].get("data_mode", "live")} for row in rows]
    return {"user": principal.user, "memberships": memberships, "csrf_token": request.cookies.get(CSRF_COOKIE, "")}


def login(request, response, data):
    origin_check(request)
    email = data["email"].strip().lower()
    ip = request.client.host if request.client else "unknown"
    # Durable rate limiting, shared across workers. Tokens are never logged.
    with transaction() as repo:
        repo.advisory(f"login:{email}:{ip}")
        table = repo.table("pharma_login_attempt")
        count = len(repo.connection.execute(select(table.c.id).where(table.c.identity_hash == text_hash(email + ip), table.c.created_at > now() - timedelta(minutes=15))).all())
        require(count < 10, "RATE_LIMITED", "登录尝试过多，请稍后再试", 429)
        repo.connection.execute(table.insert().values(identity_hash=text_hash(email + ip)))
    with transaction() as repo:
        users = repo.rows("app_user", email=email)
        user = users[0] if users else None
        try:
            valid = PASSWORDS.verify(user["password_hash"] if user else DUMMY_HASH, data["password"])
        except VerificationError:
            valid = False
        require(valid and user and user["is_active"], "AUTH_REQUIRED", "邮箱或密码不正确", 401)
        repo.advisory(f"login:{email}:{ip}")
        attempts = repo.table("pharma_login_attempt")
        repo.connection.execute(attempts.delete().where(attempts.c.identity_hash == text_hash(email + ip)))
        token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
        session = repo.add("app_session", user_id=user["id"], token_hash=text_hash(token), csrf_hash=text_hash(csrf), expires_at=now() + timedelta(hours=12))
    secure = request.url.scheme == "https" or os.environ.get("PHARMA_COOKIE_SECURE", "true") == "true"
    if not secure:
        require(urlsplit(str(request.base_url)).hostname in {"localhost", "127.0.0.1", "testserver"}, "HTTPS_REQUIRED", "公网登录需要 HTTPS", 403)
    for name, value, http_only in [(COOKIE, token, True), (CSRF_COOKIE, csrf, False)]:
        response.set_cookie(name, value, httponly=http_only, secure=secure, samesite="lax", max_age=43200, path="/api/pharma")
    principal = Principal({k: user[k] for k in ["id", "email", "display_name", "is_active"]}, session)
    result = me(request, principal)
    result["csrf_token"] = csrf
    return result
