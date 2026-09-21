"""Operator-only migration/account/fixture commands. No public registration."""

import argparse
import json
import os
import secrets
from pathlib import Path

from alembic import command
from alembic.config import Config

from .db import load_settings, transaction


def migrate():
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    command.upgrade(config, "head")


def create_account(email, name, role, workspace_id, password=None):
    from .auth import PASSWORDS

    password = password or secrets.token_urlsafe(24)
    with transaction(workspace_id) as repo:
        existing = repo.rows("app_user", email=email.lower())
        user = existing[0] if existing else repo.add("app_user", email=email.lower(), display_name=name, password_hash=PASSWORDS.hash(password))
        if not repo.rows("membership", user_id=user["id"]):
            repo.add("membership", user_id=user["id"], role=role)
    return {"email": email, "password": password if not existing else "unchanged", "workspace_id": workspace_id, "role": role}


def seed_demo(day=3, account_file=None):
    from .seed import seed

    with transaction() as repo:
        workspaces = repo.rows("workspace", name="PharmaScope 演示研究组")
        workspace = workspaces[0] if workspaces else repo.add("workspace", name="PharmaScope 演示研究组", settings={"data_mode": "demo"})
        isolated = repo.rows("workspace", name="隔离验证组")
        if not isolated:
            repo.add("workspace", name="隔离验证组", settings={"data_mode": "demo"})
    accounts = []
    for role, name in [("analyst", "研究分析员"), ("reviewer", "独立审核员"), ("admin", "研究管理员")]:
        accounts.append(create_account(f"{role}@pharmascope.invalid", name, role, workspace["id"]))
    with transaction(workspace["id"]) as repo:
        owner = repo.rows("app_user", email="analyst@pharmascope.invalid")[0]
        seed(repo, owner["id"], day)
    if account_file:
        file = Path(account_file)
        file.parent.mkdir(parents=True, exist_ok=True)
        if not file.exists():
            fd = os.open(file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump(accounts, out, ensure_ascii=False, indent=2)
    print(f"Demo workspace {workspace['id']}; day D{day}; random credentials stored privately.")


def main():
    load_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["migrate", "seed-demo", "create-user"])
    parser.add_argument("--day", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--accounts-file", default="../.deer-flow/pharma/accounts.json")
    parser.add_argument("--email")
    parser.add_argument("--name", default="研究人员")
    parser.add_argument("--role", choices=["reader", "analyst", "reviewer", "admin"], default="analyst")
    parser.add_argument("--workspace")
    args = parser.parse_args()
    if args.action == "migrate":
        migrate()
    elif args.action == "seed-demo":
        seed_demo(args.day, args.accounts_file)
    else:
        import getpass

        create_account(args.email, args.name, args.role, args.workspace, getpass.getpass("New password: "))
        print("Account created.")


if __name__ == "__main__":
    main()
