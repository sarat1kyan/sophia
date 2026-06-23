import json
import logging
import uuid
from typing import Any

from aiogram import Bot

from storage import db
from core.agent import Agent
from core import workspace as ws_mod
from streaming.streamer import AgentStreamer
from transport.local_runner import LocalRunner
from transport.ssh_runner import SSHRunner

log = logging.getLogger(__name__)

_agents: dict[str, Agent] = {}
_bot: Bot | None = None
_config: dict = {}


def init(bot: Bot, config: dict) -> None:
    global _bot, _config
    _bot = bot
    _config = config


async def load_agents_from_db() -> None:
    rows = await db.fetchall("SELECT * FROM agents WHERE status NOT IN ('done','error')")
    for row in rows:
        agent = await _row_to_agent(row)
        _agents[agent.agent_id] = agent
    log.info("Loaded %d agents from DB", len(_agents))


def _parse_settings(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


async def _row_to_agent(row: Any) -> Agent:
    workspace = None
    runner: LocalRunner | SSHRunner | None = None

    if row["workspace_id"]:
        workspace = await ws_mod.get_workspace(row["workspace_id"])

    if workspace:
        if workspace["runner_type"] == "ssh" and workspace["ssh_host_id"]:
            ssh = await ws_mod.get_ssh_host(workspace["ssh_host_id"])
            if ssh:
                runner = SSHRunner(
                    host=ssh["host"],
                    port=ssh["port"],
                    username=ssh["username"],
                    key_path=ssh["key_path"],
                    password=ssh["password"],
                    claude_path=_config.get("claude", {}).get("cli_path", "claude"),
                    default_flags=_config.get("claude", {}).get("default_flags", []),
                )
        else:
            runner = _make_local_runner()
    else:
        runner = _make_local_runner()

    agent = Agent(
        agent_id=row["id"],
        name=row["name"],
        role=row["role"],
        system_prompt=row["system_prompt"],
        workspace_path=workspace["path"] if workspace else "/tmp",
        runner=runner,
        status=row["status"],
        group_id=row["group_id"],
        settings=_parse_settings(row["settings"] if "settings" in row.keys() else None),
    )
    return agent


async def create_agent(
    name: str,
    role: str,
    system_prompt: str,
    workspace_id: int | None = None,
    group_id: int | None = None,
    settings: dict | None = None,
) -> Agent:
    agent_id = str(uuid.uuid4())
    workspace_path = "/tmp"
    runner: LocalRunner | SSHRunner

    if workspace_id:
        workspace = await ws_mod.get_workspace(workspace_id)
        if workspace:
            workspace_path = workspace["path"]
            if workspace["runner_type"] == "ssh" and workspace["ssh_host_id"]:
                ssh = await ws_mod.get_ssh_host(workspace["ssh_host_id"])
                if ssh:
                    runner = SSHRunner(
                        host=ssh["host"],
                        port=ssh["port"],
                        username=ssh["username"],
                        key_path=ssh["key_path"],
                        password=ssh["password"],
                        claude_path=_config.get("claude", {}).get("cli_path", "claude"),
                        default_flags=_config.get("claude", {}).get("default_flags", []),
                    )
                else:
                    runner = _make_local_runner()
            else:
                runner = _make_local_runner()
        else:
            runner = _make_local_runner()
    else:
        runner = _make_local_runner()

    settings_json = json.dumps(settings) if settings else None
    agent = Agent(
        agent_id=agent_id,
        name=name,
        role=role,
        system_prompt=system_prompt,
        workspace_path=workspace_path,
        runner=runner,
        status="idle",
        group_id=group_id,
        settings=settings or {},
    )

    await db.execute(
        """INSERT INTO agents (id, name, role, system_prompt, workspace_id, status, group_id, settings)
           VALUES (?,?,?,?,?,?,?,?)""",
        (agent_id, name, role, system_prompt, workspace_id, "idle", group_id, settings_json),
    )

    _agents[agent_id] = agent
    log.info("Agent created: %s (%s)", name, agent_id)
    return agent


def _make_local_runner() -> LocalRunner:
    claude_cfg = _config.get("claude", {})
    return LocalRunner(
        claude_path=claude_cfg.get("cli_path", "claude"),
        default_flags=claude_cfg.get("default_flags", []),
        run_as_user=claude_cfg.get("run_as_user"),
    )


async def start_agent(agent_id: str, prompt: str, chat_id: int, resume: bool = False) -> bool:
    agent = _agents.get(agent_id)
    if not agent:
        row = await db.fetchone("SELECT * FROM agents WHERE id = ?", (agent_id,))
        if not row:
            return False
        agent = await _row_to_agent(row)
        agent.status = "idle"
        _agents[agent_id] = agent
    if agent.status == "running":
        return False

    # Mark running immediately (before launching the task) to prevent double-start race
    agent.status = "running"

    if _bot is None:
        raise RuntimeError("orchestrator.init() must be called before start_agent()")

    chunk_lines = _config.get("sophia", {}).get("stream_chunk_lines", 1)
    if agent.role == "orchestrator":
        stream_mode = "tools"
    else:
        stream_mode = agent.settings.get("stream_mode", "full")
    streamer = AgentStreamer(_bot, chat_id, agent.name, chunk_lines, mode=stream_mode)

    async def notify_cb(event: str, data: str) -> None:
        if event == "approval" and _bot:
            req_id_str, prompt_text = data.split(":", 1)
            from bot.keyboards import approval_keyboard
            await _bot.send_message(
                chat_id,
                f"⚠️ <b>[{agent.name}]</b> Approval needed:\n\n"
                f"<code>{prompt_text[:300]}</code>\n\n"
                f"Request ID: <code>{req_id_str}</code>",
                reply_markup=approval_keyboard(int(req_id_str)),
                parse_mode="HTML",
            )

    agent.set_notify(notify_cb)
    agent.launch(prompt, streamer, resume=resume)
    return True


async def update_agent_settings(agent_id: str, settings: dict) -> bool:
    settings_json = json.dumps(settings)
    cur = await db.execute(
        "UPDATE agents SET settings=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (settings_json, agent_id),
    )
    agent = _agents.get(agent_id)
    if agent:
        agent.settings = settings
    return cur.rowcount > 0


async def update_agent_system_prompt(agent_id: str, system_prompt: str) -> bool:
    cur = await db.execute(
        "UPDATE agents SET system_prompt=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (system_prompt, agent_id),
    )
    agent = _agents.get(agent_id)
    if agent:
        agent.system_prompt = system_prompt
    return cur.rowcount > 0


async def clone_agent(source_id: str, new_name: str) -> Agent | None:
    row = await db.fetchone(
        "SELECT * FROM agents WHERE id=?", (source_id,)
    )
    if not row:
        return None
    return await create_agent(
        name=new_name,
        role=row["role"],
        system_prompt=row["system_prompt"],
        workspace_id=row["workspace_id"],
        group_id=row["group_id"],
        settings=_parse_settings(row["settings"] if "settings" in row.keys() else None),
    )


async def stop_agent(agent_id: str) -> bool:
    agent = _agents.get(agent_id)
    if not agent:
        return False
    await agent.stop()
    return True


async def kill_agent(agent_id: str) -> bool:
    agent = _agents.get(agent_id)
    if not agent:
        return False
    await agent.kill()
    return True


async def stop_all_agents() -> int:
    count = 0
    for agent in list(_agents.values()):
        if agent.status == "running":
            await agent.stop()
            count += 1
    return count


async def kill_all_agents() -> int:
    count = 0
    for agent in list(_agents.values()):
        if agent.status == "running":
            await agent.kill()
            count += 1
    return count


async def delete_agent(agent_id: str) -> bool:
    agent = _agents.get(agent_id)
    if agent:
        await agent.kill()
        _agents.pop(agent_id, None)
    cur = await db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
    return cur.rowcount > 0


async def inject_prompt(agent_id: str, text: str) -> bool:
    agent = _agents.get(agent_id)
    if not agent:
        return False
    await agent.inject_prompt(text)
    return True


def get_agent(agent_id: str) -> Agent | None:
    return _agents.get(agent_id)


async def list_agents() -> list:
    return await db.fetchall(
        """SELECT a.*, w.name as workspace_name, w.path as workspace_path
           FROM agents a
           LEFT JOIN workspaces w ON a.workspace_id = w.id
           ORDER BY a.created_at DESC"""
    )


async def agent_stats() -> dict:
    rows = await db.fetchall(
        "SELECT status, COUNT(*) as cnt FROM agents GROUP BY status"
    )
    stats = {r["status"]: r["cnt"] for r in rows}
    running = sum(1 for a in _agents.values() if a.status == "running")
    return {**stats, "in_memory": len(_agents), "actually_running": running}


async def shutdown_all() -> None:
    for agent in list(_agents.values()):
        await agent.stop()
    log.info("All agents stopped")
