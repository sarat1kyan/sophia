"""Tests for core/meta_commands.execute_command() — all branches."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.meta_commands import execute_command


def _cmd(cmd_type: str, **args) -> dict:
    return {"type": cmd_type, "args": args}


# ── CREATE_WORKSPACE ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_workspace_success():
    with patch("os.makedirs"), \
         patch("core.workspace.create_workspace", new=AsyncMock(return_value=5)):
        result = await execute_command(_cmd("CREATE_WORKSPACE", name="proj", path="/workspaces/proj"), 1)
    assert "✅" in result
    assert "proj" in result

@pytest.mark.asyncio
async def test_create_workspace_oserror_returns_error():
    with patch("os.makedirs", side_effect=OSError("permission denied")):
        result = await execute_command(_cmd("CREATE_WORKSPACE", name="proj", path="/no/access"), 1)
    assert "❌" in result
    assert "permission denied" in result

@pytest.mark.asyncio
async def test_create_workspace_default_path_uses_name():
    captured_path = []
    def fake_makedirs(path, exist_ok=False):
        captured_path.append(path)
    with patch("os.makedirs", side_effect=fake_makedirs), \
         patch("core.workspace.create_workspace", new=AsyncMock(return_value=1)):
        result = await execute_command(_cmd("CREATE_WORKSPACE", name="myws"), 1)
    assert "myws" in captured_path[0]
    assert "✅" in result

@pytest.mark.asyncio
async def test_create_workspace_path_in_result():
    with patch("os.makedirs"), \
         patch("core.workspace.create_workspace", new=AsyncMock(return_value=3)):
        result = await execute_command(_cmd("CREATE_WORKSPACE", name="x", path="/workspaces/x"), 1)
    assert "/workspaces/x" in result


# ── CREATE_AGENT ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_agent_no_workspace_succeeds():
    with patch("storage.db.fetchone", new=AsyncMock(return_value=None)), \
         patch("core.orchestrator.create_agent", new=AsyncMock(return_value=MagicMock())):
        result = await execute_command(
            _cmd("CREATE_AGENT", name="Dev", role="coder", template="Coder"), 1
        )
    assert "✅" in result
    assert "Dev" in result

@pytest.mark.asyncio
async def test_create_agent_workspace_not_found_returns_error():
    with patch("storage.db.fetchone", new=AsyncMock(return_value=None)):
        result = await execute_command(
            _cmd("CREATE_AGENT", name="Dev", role="coder", template="Coder", workspace="missing_ws"), 1
        )
    assert "❌" in result
    assert "missing_ws" in result

@pytest.mark.asyncio
async def test_create_agent_workspace_found_passes_ws_id():
    ws_row = {"id": 7}
    captured = {}
    async def fake_create(**kwargs):
        captured.update(kwargs)
        return MagicMock()
    call_n = [0]
    async def mock_fetchone(q, p=()):
        # First call: workspace lookup → found; second call: template → not found
        call_n[0] += 1
        return ws_row if call_n[0] == 1 else None
    with patch("storage.db.fetchone", side_effect=mock_fetchone), \
         patch("core.orchestrator.create_agent", side_effect=fake_create):
        await execute_command(
            _cmd("CREATE_AGENT", name="Dev", role="coder", template="Coder", workspace="myproj"), 1
        )
    assert captured.get("workspace_id") == 7

@pytest.mark.asyncio
async def test_create_agent_skip_permissions_false():
    captured = {}
    async def fake_create(**kwargs):
        captured.update(kwargs)
        return MagicMock()
    with patch("storage.db.fetchone", new=AsyncMock(return_value=None)), \
         patch("core.orchestrator.create_agent", side_effect=fake_create):
        await execute_command(
            _cmd("CREATE_AGENT", name="A", role="tester", template="T", skip_permissions="false"), 1
        )
    assert captured["settings"]["skip_permissions"] is False

@pytest.mark.asyncio
async def test_create_agent_skip_permissions_no():
    captured = {}
    async def fake_create(**kwargs):
        captured.update(kwargs)
        return MagicMock()
    with patch("storage.db.fetchone", new=AsyncMock(return_value=None)), \
         patch("core.orchestrator.create_agent", side_effect=fake_create):
        await execute_command(
            _cmd("CREATE_AGENT", name="A", role="tester", template="T", skip_permissions="no"), 1
        )
    assert captured["settings"]["skip_permissions"] is False

@pytest.mark.asyncio
async def test_create_agent_skip_permissions_default_true():
    captured = {}
    async def fake_create(**kwargs):
        captured.update(kwargs)
        return MagicMock()
    with patch("storage.db.fetchone", new=AsyncMock(return_value=None)), \
         patch("core.orchestrator.create_agent", side_effect=fake_create):
        await execute_command(
            _cmd("CREATE_AGENT", name="A", role="coder", template="Coder"), 1
        )
    assert captured["settings"]["skip_permissions"] is True

@pytest.mark.asyncio
async def test_create_agent_template_system_prompt_used():
    tpl_row = {"system_prompt": "You are a coder."}
    captured = {}
    async def fake_create(**kwargs):
        captured.update(kwargs)
        return MagicMock()
    call_n = [0]
    async def mock_fetchone(q, p=()):
        call_n[0] += 1
        # First call might be workspace (no workspace arg here → skip), or template
        return tpl_row  # always return template for simplicity
    with patch("storage.db.fetchone", side_effect=mock_fetchone), \
         patch("core.orchestrator.create_agent", side_effect=fake_create):
        await execute_command(
            _cmd("CREATE_AGENT", name="A", role="coder", template="Coder"), 1
        )
    assert captured.get("system_prompt") == "You are a coder."


# ── RUN_AGENT ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_agent_missing_name_returns_error():
    result = await execute_command(_cmd("RUN_AGENT", prompt="do stuff"), 1)
    assert "❌" in result
    assert "name" in result.lower()

@pytest.mark.asyncio
async def test_run_agent_missing_prompt_returns_error():
    result = await execute_command(_cmd("RUN_AGENT", name="Dev"), 1)
    assert "❌" in result
    assert "prompt" in result.lower()

@pytest.mark.asyncio
async def test_run_agent_not_found_returns_error():
    with patch("storage.db.fetchone", new=AsyncMock(return_value=None)):
        result = await execute_command(_cmd("RUN_AGENT", name="Ghost", prompt="do it"), 1)
    assert "❌" in result
    assert "Ghost" in result

@pytest.mark.asyncio
async def test_run_agent_started_successfully():
    with patch("storage.db.fetchone", new=AsyncMock(return_value={"id": "abc-123"})), \
         patch("core.orchestrator.start_agent", new=AsyncMock(return_value=True)):
        result = await execute_command(_cmd("RUN_AGENT", name="Dev", prompt="build it"), 1)
    assert "🚀" in result
    assert "Dev" in result

@pytest.mark.asyncio
async def test_run_agent_already_running_returns_warning():
    with patch("storage.db.fetchone", new=AsyncMock(return_value={"id": "abc-123"})), \
         patch("core.orchestrator.start_agent", new=AsyncMock(return_value=False)):
        result = await execute_command(_cmd("RUN_AGENT", name="Dev", prompt="build it"), 1)
    assert "⚠️" in result or "already running" in result.lower()

@pytest.mark.asyncio
async def test_run_agent_passes_chat_id():
    captured_chat_id = []
    async def fake_start(agent_id, prompt, chat_id):
        captured_chat_id.append(chat_id)
        return True
    with patch("storage.db.fetchone", new=AsyncMock(return_value={"id": "abc-123"})), \
         patch("core.orchestrator.start_agent", side_effect=fake_start):
        await execute_command(_cmd("RUN_AGENT", name="Dev", prompt="task"), 42)
    assert captured_chat_id[0] == 42


# ── LIST_AGENTS ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_agents_empty():
    with patch("core.orchestrator.list_agents", new=AsyncMock(return_value=[])):
        result = await execute_command(_cmd("LIST_AGENTS"), 1)
    assert "No agents" in result

@pytest.mark.asyncio
async def test_list_agents_shows_all_agents():
    agents = [
        {"name": "Alpha", "role": "coder", "status": "running"},
        {"name": "Beta",  "role": "tester", "status": "done"},
        {"name": "Gamma", "role": "coder", "status": "idle"},
    ]
    with patch("core.orchestrator.list_agents", new=AsyncMock(return_value=agents)):
        result = await execute_command(_cmd("LIST_AGENTS"), 1)
    assert "Alpha" in result
    assert "Beta" in result
    assert "Gamma" in result

@pytest.mark.asyncio
async def test_list_agents_status_icons():
    agents = [
        {"name": "R", "role": "coder", "status": "running"},
        {"name": "D", "role": "coder", "status": "done"},
        {"name": "E", "role": "coder", "status": "error"},
        {"name": "I", "role": "coder", "status": "idle"},
    ]
    with patch("core.orchestrator.list_agents", new=AsyncMock(return_value=agents)):
        result = await execute_command(_cmd("LIST_AGENTS"), 1)
    assert "🟢" in result  # running
    assert "✅" in result  # done
    assert "🔴" in result  # error
    assert "💤" in result  # idle


# ── LIST_WORKSPACES ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_workspaces_empty():
    with patch("core.workspace.list_workspaces", new=AsyncMock(return_value=[])):
        result = await execute_command(_cmd("LIST_WORKSPACES"), 1)
    assert "No workspaces" in result

@pytest.mark.asyncio
async def test_list_workspaces_shows_names_and_paths():
    workspaces = [
        {"name": "myproject", "path": "/workspaces/myproject"},
        {"name": "other",     "path": "/workspaces/other"},
    ]
    with patch("core.workspace.list_workspaces", new=AsyncMock(return_value=workspaces)):
        result = await execute_command(_cmd("LIST_WORKSPACES"), 1)
    assert "myproject" in result
    assert "/workspaces/myproject" in result
    assert "other" in result


# ── Unknown command ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unknown_command_type_returns_warning():
    result = await execute_command(_cmd("TELEPORT_AGENT"), 1)
    assert "⚠️" in result or "Unknown" in result
    assert "TELEPORT_AGENT" in result
