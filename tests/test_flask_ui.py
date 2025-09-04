from __future__ import annotations

import pytest

from src.flask_ui import create_app


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("LOCAL_DEV", "true")
    monkeypatch.setenv("DYNAMODB_LOCAL_ENDPOINT", "http://localhost:8000")
    monkeypatch.setenv("CONFIG_TABLE_NAME", "agentcore-test-config")
    monkeypatch.setenv("TABLE_NAME", "agentcore-approval-log-test")


@pytest.fixture
def _stub_config_store(monkeypatch: pytest.MonkeyPatch) -> None:
    # Use in-memory storage to avoid DynamoDB for these tests
    storage: dict[str, list[dict[str, object]]] = {"servers": []}

    from src import config_store as cs
    from src import flask_ui as ui

    def fake_get_mcp_servers():  # type: ignore[no-redef]
        return cs.MCPServersConfig(
            servers=[cs.MCPServer(**d) for d in storage["servers"]]
        )

    def fake_put_mcp_servers(servers):  # type: ignore[no-redef]
        storage["servers"] = [s.model_dump() for s in servers]

    monkeypatch.setattr(
        "src.config_store.get_mcp_servers", fake_get_mcp_servers
    )
    monkeypatch.setattr(
        "src.config_store.put_mcp_servers", fake_put_mcp_servers
    )
    # Also patch the symbols imported into the Flask module
    monkeypatch.setattr(ui, "get_mcp_servers", fake_get_mcp_servers)
    monkeypatch.setattr(ui, "put_mcp_servers", fake_put_mcp_servers)


def test_flask_routes_smoke() -> None:
    app = create_app()
    client = app.test_client()
    assert client.get("/").status_code == 200
    assert client.get("/servers").status_code == 200
    assert client.get("/policies").status_code == 200
    assert client.get("/approvals").status_code == 200


def test_servers_save_and_load_disabled_tools(
    _stub_config_store: None,
) -> None:
    from src.config_store import get_mcp_servers

    app = create_app()
    client = app.test_client()

    # Post a single server with disabled tools
    resp = client.post(
        "/servers",
        data={
            "alias": ["google"],
            "path": ["/abs/path/google_mcp/google_admin/mcp_server.py"],
            "enabled_0": "on",
            "disabled_tools": [
                "delete_user, remove_role , google__files_delete"
            ],
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    cfg = get_mcp_servers()
    assert len(cfg.servers) == 1
    s = cfg.servers[0]
    # Normalized to short names
    assert sorted(s.disabled_tools) == [
        "delete_user",
        "files_delete",
        "remove_role",
    ]


def test_servers_save_command_args(_stub_config_store: None) -> None:
    from src.config_store import get_mcp_servers

    app = create_app()
    client = app.test_client()

    resp = client.post(
        "/servers",
        data={
            "alias": ["calculator"],
            "path": [""],
            "command": ["uvx"],
            "args": ["mcp-server-calculator"],
            "enabled_0": "on",
            "disabled_tools": [""],
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    cfg = get_mcp_servers()
    assert len(cfg.servers) == 1
    s = cfg.servers[0]
    assert s.alias == "calculator"
    assert s.command == "uvx"
    assert s.args == ["mcp-server-calculator"]
    assert s.enabled is True


def test_servers_env_parsing_and_preservation(
    _stub_config_store: None,
) -> None:
    from src.config_store import MCPServer, MCPServersConfig, get_mcp_servers

    app = create_app()
    client = app.test_client()

    # Seed existing config with octagon env

    existing = MCPServersConfig(
        servers=[
            MCPServer(
                alias="octagon",
                path="/abs/path/octagon/mcp_server.py",
                enabled=True,
                env={"OCTAGON_API_KEY": "keepme", "REGION": "us-east-1"},
            )
        ]
    )

    # Inject storage via the stubbed put/get in this test module's fixture storage
    # by calling the patched put
    from src.flask_ui import put_mcp_servers as patched_put

    patched_put(existing.servers)

    # 1) Post update WITHOUT env for same alias -> should preserve existing env
    resp = client.post(
        "/servers",
        data={
            "alias": ["octagon"],
            "path": ["/abs/path/octagon/mcp_server.py"],
            "enabled_0": "on",
            # no env field provided
            "disabled_tools": [""],
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    cfg = get_mcp_servers()
    assert len(cfg.servers) == 1
    s = cfg.servers[0]
    assert s.alias == "octagon"
    assert s.env == {"OCTAGON_API_KEY": "keepme", "REGION": "us-east-1"}

    # 2) Post update WITH env block -> should replace env with parsed keys
    resp = client.post(
        "/servers",
        data={
            "alias": ["octagon"],
            "path": ["/abs/path/octagon/mcp_server.py"],
            "enabled_0": "on",
            "env": ["OCTAGON_API_KEY=newvalue\n# comment\nEXTRA = 123"],
            "disabled_tools": [""],
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    cfg = get_mcp_servers()
    assert len(cfg.servers) == 1
    s = cfg.servers[0]
    assert s.env == {"OCTAGON_API_KEY": "newvalue", "EXTRA": "123"}
