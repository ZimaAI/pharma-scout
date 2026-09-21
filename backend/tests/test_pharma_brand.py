from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from app.pharma import cli


@pytest.mark.parametrize("existing_name", ["PharmaScope 演示研究组", "PharmaScount 演示研究组"])
def test_seed_demo_reuses_existing_workspace_after_rename(monkeypatch, existing_name):
    workspace = {"id": "existing-workspace", "name": existing_name}
    repo = Mock()

    def rows(table, **filters):
        if table == "workspace":
            return [workspace] if filters["name"] == workspace["name"] else []
        return [{"id": "existing-analyst"}]

    def update(table, identifier, **values):
        assert table == "workspace" and identifier == workspace["id"]
        workspace.update(values)
        return workspace

    repo.rows.side_effect = rows
    repo.update.side_effect = update

    @contextmanager
    def transaction(*args):
        yield repo

    monkeypatch.setattr(cli, "transaction", transaction)
    monkeypatch.setattr(cli, "create_account", Mock(return_value={}))
    seed = Mock()
    monkeypatch.setattr("app.pharma.seed.seed", seed)
    cli.seed_demo()
    cli.seed_demo()
    assert workspace["name"] == "PharmaScount 演示研究组"
    assert all(call.kwargs.get("name") == "隔离验证组" for call in repo.add.call_args_list)
    assert all(call.args[3] == "existing-workspace" for call in cli.create_account.call_args_list)
    assert seed.call_count == 2
