"""Explicit opt-in PostgreSQL fixtures; never truncate shared database tables."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import make_url

from app.pharma import db


@pytest.fixture(scope="module")
def database():
    url = os.environ.get("PHARMA_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PHARMA_TEST_DATABASE_URL is required for PostgreSQL integration")
    parsed = make_url(url)
    assert parsed.database and parsed.database.endswith("_test"), "Integration tests require a dedicated *_test database"
    schema = "pharma_test_" + uuid4().hex
    admin_engine = create_engine(url)
    with admin_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    test_engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    config = Config()
    config.set_main_option("script_location", str(Path(db.__file__).parent / "migrations"))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(db, "engine", lambda: test_engine)
        try:
            command.upgrade(config, "head")
            command.upgrade(config, "head")
            metadata = MetaData()
            metadata.reflect(bind=test_engine)
            patch.setattr(db, "tables", lambda: metadata.tables)
            yield test_engine
        finally:
            test_engine.dispose()
            with admin_engine.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            admin_engine.dispose()


@pytest.fixture
def repo(database):
    with database.connect() as connection:
        transaction = connection.begin()
        try:
            global_repo = db.Repository(connection)
            workspace = global_repo.add("workspace", name="Synthetic persistence tests", settings={"data_mode": "demo"})
            user = global_repo.add("app_user", email=f"{uuid4().hex}@pharma-test.invalid", display_name="Synthetic analyst", password_hash="not-a-login-credential")
            scoped = db.Repository(connection, workspace["id"])
            scoped.add("membership", user_id=user["id"], role="analyst")
            yield scoped, user["id"]
        finally:
            transaction.rollback()
