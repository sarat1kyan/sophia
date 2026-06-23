"""
Meta-command engine for Sophia (orchestrator-role agents).

Sophia emits [[SOPHIA:COMMAND key="value"]] markers in her output.
This module parses those markers and executes the corresponding actions.
"""
import logging
import os
import re
from html import escape

log = logging.getLogger(__name__)

# Matches: [[SOPHIA:COMMAND_NAME key="value" ...]]
# Arg section uses ((?:[^"\]]|"[^"]*")*) so quoted values can contain ] safely.
_CMD_RE = re.compile(r'\[\[SOPHIA:(\w+)((?:[^"\]]|"[^"]*")*)\]\]')
_ARG_RE = re.compile(r'(\w+)="([^"]*)"')


def parse_commands(text: str) -> list[dict]:
    """Return all [[SOPHIA:...]] commands found in text."""
    results = []
    for m in _CMD_RE.finditer(text):
        cmd_type = m.group(1).upper()
        args = dict(_ARG_RE.findall(m.group(2)))
        results.append({"type": cmd_type, "args": args, "raw": m.group(0)})
    return results


def strip_commands(text: str) -> str:
    """Remove all [[SOPHIA:...]] markers from text so they don't appear in chat."""
    return _CMD_RE.sub("", text).strip()


async def execute_command(cmd: dict, chat_id: int) -> str:
    """Execute a parsed SOPHIA command. Returns a human-readable status string."""
    from core import orchestrator
    from core import workspace as ws_mod
    from storage import db

    cmd_type = cmd["type"]
    args = cmd["args"]

    if cmd_type == "CREATE_WORKSPACE":
        name = args.get("name", "workspace")
        path = args.get("path", f"/tmp/sophia_{name}")
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as e:
            return f"❌ Could not create directory <code>{escape(path)}</code>: {escape(str(e))}"
        ws_id = await ws_mod.create_workspace(name, path)
        log.info("Sophia created workspace '%s' at %s (id=%d)", name, path, ws_id)
        return f"✅ Workspace <b>{escape(name)}</b> created at <code>{escape(path)}</code>"

    elif cmd_type == "CREATE_AGENT":
        name = args.get("name", "Agent")
        role = args.get("role", "coder")
        template_name = args.get("template", "Coder")
        workspace_name = args.get("workspace")
        skip_perms = args.get("skip_permissions", "true").lower() not in ("false", "no", "0", "off")

        ws_id = None
        if workspace_name:
            ws_row = await db.fetchone(
                "SELECT id FROM workspaces WHERE name=? ORDER BY id DESC LIMIT 1",
                (workspace_name,),
            )
            if ws_row:
                ws_id = ws_row["id"]
            else:
                return f"❌ Workspace <b>{escape(workspace_name)}</b> not found - create it first"

        tpl = await db.fetchone(
            "SELECT system_prompt FROM templates WHERE name=? LIMIT 1", (template_name,)
        )
        system_prompt = tpl["system_prompt"] if tpl else ""

        settings = {"skip_permissions": skip_perms}
        agent_obj = await orchestrator.create_agent(
            name=name,
            role=role,
            system_prompt=system_prompt,
            workspace_id=ws_id,
            settings=settings,
        )
        log.info("Sophia created agent '%s' (role=%s, ws_id=%s)", name, role, ws_id)
        return f"✅ Agent <b>{escape(name)}</b> [{escape(role)}] created"

    elif cmd_type == "RUN_AGENT":
        name = args.get("name")
        prompt = args.get("prompt", "")
        if not name:
            return "❌ RUN_AGENT requires a name argument"
        if not prompt:
            return "❌ RUN_AGENT requires a prompt argument"

        row = await db.fetchone(
            "SELECT id FROM agents WHERE name=? ORDER BY created_at DESC LIMIT 1", (name,)
        )
        if not row:
            return f"❌ Agent <b>{escape(name)}</b> not found - create it first"

        ok = await orchestrator.start_agent(row["id"], prompt, chat_id)
        if ok:
            log.info("Sophia started agent '%s' with prompt: %s", name, prompt[:80])
            return f"🚀 Agent <b>{escape(name)}</b> started"
        return f"⚠️ Agent <b>{escape(name)}</b> is already running"

    elif cmd_type == "LIST_AGENTS":
        agents = await orchestrator.list_agents()
        if not agents:
            return "📋 No agents found."
        lines = ["📋 <b>Current agents:</b>"]
        icons = {"idle": "💤", "running": "🟢", "done": "✅", "error": "🔴"}
        for a in agents:
            icon = icons.get(a["status"], "❓")
            lines.append(f"  {icon} <b>{escape(a['name'])}</b> [{escape(a['role'])}] - {a['status']}")
        return "\n".join(lines)

    elif cmd_type == "LIST_WORKSPACES":
        workspaces = await ws_mod.list_workspaces()
        if not workspaces:
            return "📁 No workspaces found."
        lines = ["📁 <b>Current workspaces:</b>"]
        for w in workspaces:
            lines.append(f"  <b>{escape(w['name'])}</b> - <code>{escape(w['path'])}</code>")
        return "\n".join(lines)

    else:
        return f"⚠️ Unknown command: {cmd_type}"
