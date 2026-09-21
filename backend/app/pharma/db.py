"""SQLAlchemy Core repository. Every business lookup is explicitly workspace scoped."""

import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from fastapi.encoders import jsonable_encoder
from sqlalchemy import MetaData, create_engine, select, text

from .errors import require


def now():
    return datetime.now(UTC)


def uid():
    return str(uuid.uuid4())


def canonical(value):
    return json.dumps(jsonable_encoder(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def text_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def load_settings():
    from dotenv import load_dotenv

    root = Path(__file__).resolve().parents[3]
    load_dotenv(root / ".deer-flow/pharma/private.env", override=False)


@lru_cache
def engine():
    load_settings()
    url = os.environ.get("PHARMA_DATABASE_URL")
    require(url, "PHARMA_NOT_CONFIGURED", "医药研究数据库尚未配置", 503)
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


@lru_cache
def tables():
    metadata = MetaData()
    metadata.reflect(bind=engine())
    return metadata.tables


class Repository:
    def __init__(self, connection, workspace_id=None):
        self.connection = connection
        self.workspace_id = workspace_id

    def table(self, name):
        return tables()[name]

    def query(self, name, /, **filters):
        table = self.table(name)
        statement = select(table)
        if "workspace_id" in table.c:
            require(self.workspace_id, "WORKSPACE_REQUIRED", "工作区上下文缺失", 500)
            statement = statement.where(table.c.workspace_id == self.workspace_id)
        for key, value in filters.items():
            statement = statement.where(table.c[key] == value)
        return statement

    def rows(self, name, /, *, order=None, limit=500, lock=False, **filters):
        statement = self.query(name, **filters)
        table = self.table(name)
        if order is not None:
            statement = statement.order_by(order)
        elif "created_at" in table.c:
            statement = statement.order_by(table.c.created_at.desc(), table.c.id.desc() if "id" in table.c else table.c.user_id)
        if lock:
            statement = statement.with_for_update()
        result = self.connection.execute(statement.limit(limit)).mappings().all()
        return jsonable_encoder([dict(row) for row in result])

    def get(self, name, identifier, *, lock=False):
        rows = self.rows(name, id=identifier, lock=lock, limit=1)
        require(rows)
        return rows[0]

    def add(self, name, /, **values):
        table = self.table(name)
        if "workspace_id" in table.c:
            require(self.workspace_id, "WORKSPACE_REQUIRED", "工作区上下文缺失", 500)
            values["workspace_id"] = self.workspace_id
        row = self.connection.execute(table.insert().values(**values).returning(table)).mappings().one()
        return jsonable_encoder(dict(row))

    def update(self, name, identifier, /, **values):
        table = self.table(name)
        statement = table.update().where(table.c.id == identifier)
        if "workspace_id" in table.c:
            require(self.workspace_id)
            statement = statement.where(table.c.workspace_id == self.workspace_id)
        row = self.connection.execute(statement.values(**values).returning(table)).mappings().first()
        require(row)
        return jsonable_encoder(dict(row))

    def audit(self, actor_id, action, target_type, target_id=None, **details):
        return self.add("audit_log", actor_id=actor_id, action=action, target_type=target_type, target_id=target_id, details=details)

    def advisory(self, key):
        self.connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": key})


@contextmanager
def transaction(workspace_id=None):
    with engine().begin() as connection:
        yield Repository(connection, workspace_id)
