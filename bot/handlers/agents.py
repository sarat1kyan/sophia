import json
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from core import orchestrator
from storage import db
from bot import keyboards

log = logging.getLogger(__name__)
router = Router()

STATUS_ICON = {"idle": "💤", "running": "🟢", "done": "✅", "error": "🔴", "waiting_approval": "⏳"}


class NewAgentForm(StatesGroup):
    name      = State()
    template  = State()
    workspace = State()


class InjectPromptForm(StatesGroup):
    text = State()


class StartAgentForm(StatesGroup):
    prompt = State()
    resume = State()  # internal flag


class RenameAgentForm(StatesGroup):
    agent_id = State()
    new_name = State()


class CloneAgentForm(StatesGroup):
    source_id = State()
    new_name  = State()


class EditSysPromptForm(StatesGroup):
    agent_id    = State()
    system_prompt = State()


class AgentSettingForm(StatesGroup):
    agent_id = State()
    field    = State()
    value    = State()


# ── /agents list ───────────────────────────────────────────────────────────

@router.message(Command("agents"))
async def cmd_agents(msg: Message) -> None:
    agents = await orchestrator.list_agents()
    if not agents:
        await msg.answer(
            "<b>🤖 Agents</b>\n\nNo agents yet.",
            parse_mode="HTML",
            reply_markup=keyboards.agents_list_keyboard([]),
        )
        return
    lines = ["<b>🤖 Agents</b>\n"]
    for a in agents:
        icon = STATUS_ICON.get(a["status"], "❓")
        ws = f"  📁 {a['workspace_name']}" if a["workspace_name"] else ""
        rc = a["run_count"] if "run_count" in a.keys() else 0
        lines.append(f"{icon} <b>{a['name']}</b> [{a['role']}]{ws}  <i>runs: {rc}</i>")
    lines.append("\n<i>Tap an agent to manage it.</i>")
    await msg.answer("\n".join(lines), parse_mode="HTML",
                     reply_markup=keyboards.agents_list_keyboard(agents))


# ── agent detail ───────────────────────────────────────────────────────────

@router.message(Command("agent"))
async def cmd_agent_detail(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Usage: /agent <id>")
        return
    match = await _find_agent(parts[1].strip())
    if not match:
        await msg.answer("Agent not found.")
        return
    await msg.answer(_agent_card(match), parse_mode="HTML",
                     reply_markup=keyboards.agent_detail_keyboard(match["id"], match["status"]))


@router.callback_query(F.data.startswith("agent_detail:"))
async def cb_agent_detail(cb: CallbackQuery) -> None:
    agent_id = cb.data.split(":", 1)[1]
    agents = await orchestrator.list_agents()
    match = next((a for a in agents if a["id"] == agent_id), None)
    if not match:
        await cb.answer("Agent not found.", show_alert=True)
        return
    await cb.message.edit_text(
        _agent_card(match),
        parse_mode="HTML",
        reply_markup=keyboards.agent_detail_keyboard(match["id"], match["status"]),
    )
    await cb.answer()


def _agent_card(a) -> str:
    import os
    icon = STATUS_ICON.get(a["status"], "❓")
    ws_name = a["workspace_name"] or "default"
    ws_path = a["workspace_path"] if a["workspace_path"] else "/tmp"
    path_warn = ""
    if ws_name != "default" and not os.path.isdir(ws_path):
        path_warn = f"\n⚠️ <b>Workspace path missing:</b> <code>{ws_path}</code>"
    rc = a["run_count"] if "run_count" in a.keys() else 0
    last = str(a["last_run_at"])[:16] if a["last_run_at"] else "never"
    settings = _parse_settings(a)
    settings_desc = _settings_summary(settings)
    return (
        f"<b>🤖 {a['name']}</b>\n\n"
        f"Role:      <b>{a['role']}</b>\n"
        f"Status:    {icon} <b>{a['status']}</b>\n"
        f"Workspace: 📁 {ws_name}{path_warn}\n"
        f"Runs:      {rc}  (last: {last})\n"
        f"Settings:  {settings_desc}\n"
        f"Created:   {str(a['created_at'])[:16]}\n\n"
        f"<i>System prompt:</i>\n"
        f"<code>{str(a['system_prompt'])[:200]}</code>"
    )


def _parse_settings(a) -> dict:
    raw = a["settings"] if "settings" in a.keys() else None
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _settings_summary(s: dict) -> str:
    parts = []
    if s.get("skip_permissions"):
        parts.append("skip-perms")
    stream_icon = {"full": "🔊", "tools": "🔧", "silent": "🔇"}
    mode = s.get("stream_mode", "full")
    parts.append(f"{stream_icon.get(mode, '🔊')}{mode}")
    if s.get("effort"):
        parts.append(f"effort={s['effort']}")
    if s.get("model"):
        parts.append(f"model={s['model']}")
    if s.get("timeout_seconds"):
        parts.append(f"timeout={s['timeout_seconds']}s")
    if s.get("max_budget_usd"):
        parts.append(f"budget=${s['max_budget_usd']}")
    return ", ".join(parts) if parts else "defaults"


# ── /new_agent wizard ──────────────────────────────────────────────────────

@router.message(Command("new_agent"))
async def cmd_new_agent(msg: Message, state: FSMContext) -> None:
    await state.set_state(NewAgentForm.name)
    await msg.answer(
        "🤖 <b>New Agent</b> - Step 1/3\n\nWhat should the agent be <b>named</b>?",
        parse_mode="HTML",
        reply_markup=keyboards.cancel_keyboard(),
    )


@router.message(NewAgentForm.name)
async def na_name(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    data = await state.get_data()
    await state.update_data(name=msg.text.strip())
    if "template" in data and "system_prompt" in data:
        await _ask_workspace(msg, state, step="2/2")
        return
    tpls = await db.fetchall("SELECT * FROM templates ORDER BY is_builtin DESC, name")
    await msg.answer(
        "🤖 <b>New Agent</b> - Step 2/3\n\n<b>Choose a role template:</b>",
        parse_mode="HTML",
        reply_markup=keyboards.template_picker_keyboard(tpls),
    )
    await state.set_state(NewAgentForm.template)


async def _ask_workspace(msg_or_cb, state: FSMContext, step: str = "3/3") -> None:
    ws_list = await db.fetchall("SELECT id, name, path FROM workspaces ORDER BY created_at DESC")
    if len(ws_list) == 1:
        # Auto-select when only one workspace exists
        await state.update_data(workspace_id=ws_list[0]["id"])
        data = await state.get_data()
        await _finish_create_agent(msg_or_cb, state, data, ws_list[0]["id"])
        return
    if ws_list:
        lines = [f"🤖 <b>New Agent</b> - Step {step}\n\n<b>Choose a workspace</b> or reply <code>default</code> for /tmp:\n"]
        for w in ws_list:
            lines.append(f"  • <b>#{w['id']}</b> {w['name']}  <code>{w['path']}</code>")
        text = "\n".join(lines)
    else:
        text = (
            f"🤖 <b>New Agent</b> - Step {step}\n\n"
            "No workspaces found. Reply <code>default</code> to use /tmp, "
            "or add one with /new_workspace."
        )
    if isinstance(msg_or_cb, CallbackQuery):
        await msg_or_cb.message.edit_text(text, parse_mode="HTML",
                                          reply_markup=keyboards.cancel_keyboard())
    else:
        await msg_or_cb.answer(text, parse_mode="HTML",
                               reply_markup=keyboards.cancel_keyboard())
    await state.set_state(NewAgentForm.workspace)


@router.callback_query(F.data.startswith("tpl:"), NewAgentForm.template)
async def na_template_cb(cb: CallbackQuery, state: FSMContext) -> None:
    tpl_name = cb.data.split(":", 1)[1]
    row = await db.fetchone("SELECT * FROM templates WHERE name = ?", (tpl_name,))
    if not row:
        await cb.answer("Template not found.", show_alert=True)
        return
    await state.update_data(template=tpl_name, system_prompt=row["system_prompt"])
    await _ask_workspace(cb, state)
    await cb.answer()


@router.message(NewAgentForm.template)
async def na_template_text(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    row = await db.fetchone("SELECT * FROM templates WHERE name = ?", (msg.text.strip(),))
    if not row:
        names = ", ".join(t["name"] for t in await db.fetchall("SELECT name FROM templates"))
        await msg.answer(f"Template not found. Try: {names}")
        return
    await state.update_data(template=row["name"], system_prompt=row["system_prompt"])
    await _ask_workspace(msg, state)


@router.message(NewAgentForm.workspace)
async def na_workspace(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    text = msg.text.strip()
    workspace_id = None
    if text != "default":
        rows = await db.fetchall(
            "SELECT * FROM workspaces WHERE name=? OR id=?",
            (text, text if text.isdigit() else -1),
        )
        if rows:
            workspace_id = rows[0]["id"]
        else:
            await msg.answer(
                f"Workspace '{text}' not found. Reply <code>default</code> or enter a valid workspace name/id.",
                parse_mode="HTML",
            )
            return
    data = await state.get_data()
    await _finish_create_agent(msg, state, data, workspace_id)


async def _finish_create_agent(msg_or_cb, state: FSMContext, data: dict, workspace_id: int | None) -> None:
    try:
        agent = await orchestrator.create_agent(
            name=data["name"],
            role=data.get("template", "custom"),
            system_prompt=data.get("system_prompt", ""),
            workspace_id=workspace_id,
        )
    except Exception as e:
        await state.clear()
        err = str(e)
        reply = msg_or_cb.message if isinstance(msg_or_cb, CallbackQuery) else msg_or_cb
        await reply.answer(
            f"❌ Failed to create agent: <code>{err[:200]}</code>",
            parse_mode="HTML",
            reply_markup=keyboards.back_to_menu(),
        )
        return
    await state.clear()
    await state.update_data(agent_id=agent.agent_id, chat_id=_chat_id(msg_or_cb), resume=False)
    await state.set_state(StartAgentForm.prompt)
    text = (
        f"✅ <b>Agent created!</b>\n\n"
        f"🤖 <b>{agent.name}</b> [{agent.role}]\n"
        f"ID: <code>{agent.agent_id[:8]}</code>\n\n"
        f"<b>What task should it work on?</b>\n"
        f"<i>Type your task below, or tap Cancel to set it up later.</i>"
    )
    if isinstance(msg_or_cb, CallbackQuery):
        await msg_or_cb.message.answer(text, parse_mode="HTML",
                                       reply_markup=keyboards.cancel_keyboard())
    else:
        await msg_or_cb.answer(text, parse_mode="HTML",
                               reply_markup=keyboards.cancel_keyboard())


def _chat_id(msg_or_cb) -> int:
    if isinstance(msg_or_cb, CallbackQuery):
        return msg_or_cb.message.chat.id
    return msg_or_cb.chat.id


# ── /run <name> <task> quick start ─────────────────────────────────────────

@router.message(Command("run"))
async def cmd_run(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await msg.answer(
            "Usage: /run <agent_name_or_id> <task>\n\n"
            "Example: /run coder-01 Implement the login endpoint",
            parse_mode="HTML",
        )
        return
    match = await _find_agent(parts[1])
    if not match:
        await msg.answer(f"Agent '{parts[1]}' not found. Use /agents to list all agents.")
        return
    if match["status"] == "running":
        await msg.answer(f"⚠️ <b>{match['name']}</b> is already running.", parse_mode="HTML")
        return
    ok = await orchestrator.start_agent(match["id"], parts[2], msg.chat.id)
    if ok:
        await msg.answer(
            f"🚀 <b>{match['name']}</b> started.\n\nOutput will stream here.",
            parse_mode="HTML",
        )
    else:
        await msg.answer(f"❌ Failed to start <b>{match['name']}</b>.", parse_mode="HTML")


# ── Start agent via button ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("agent_run:"))
async def cb_agent_run(cb: CallbackQuery, state: FSMContext) -> None:
    agent_id = cb.data.split(":", 1)[1]
    await state.update_data(agent_id=agent_id, chat_id=cb.message.chat.id, resume=False)
    await state.set_state(StartAgentForm.prompt)
    await cb.message.answer(
        "▶ <b>Start Agent</b>\n\nWhat task should the agent work on?",
        parse_mode="HTML",
        reply_markup=keyboards.cancel_keyboard(),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("agent_resume:"))
async def cb_agent_resume(cb: CallbackQuery, state: FSMContext) -> None:
    agent_id = cb.data.split(":", 1)[1]
    from core.session import get_last_claude_session_id
    last_sid = await get_last_claude_session_id(agent_id)
    if not last_sid:
        await cb.answer(
            "No resumable session found. Use Start for a fresh run.",
            show_alert=True,
        )
        return
    await state.update_data(agent_id=agent_id, chat_id=cb.message.chat.id, resume=True)
    await state.set_state(StartAgentForm.prompt)
    await cb.message.answer(
        "↩ <b>Resume Agent</b>\n\n"
        f"Resuming previous Claude session <code>{last_sid[:12]}…</code>\n\n"
        "What should the agent continue with?",
        parse_mode="HTML",
        reply_markup=keyboards.cancel_keyboard(),
    )
    await cb.answer()


@router.message(StartAgentForm.prompt)
async def sa_prompt(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    data = await state.get_data()
    await state.clear()
    agent_id = data["agent_id"]
    chat_id  = data.get("chat_id", msg.chat.id)
    resume   = bool(data.get("resume", False))
    ok = await orchestrator.start_agent(agent_id, msg.text.strip(), chat_id, resume=resume)
    agents = await orchestrator.list_agents()
    match  = next((a for a in agents if a["id"] == agent_id), None)
    name   = match["name"] if match else agent_id[:8]
    if ok:
        verb = "resuming" if resume else "running"
        await msg.answer(f"🚀 <b>{name}</b> is {verb}…\n\nOutput will stream here.", parse_mode="HTML")
    else:
        await msg.answer(f"❌ Could not start <b>{name}</b> (already running or not found).", parse_mode="HTML",
                         reply_markup=keyboards.back_to_menu())


# ── Inject prompt ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("agent_prompt:"))
async def cb_agent_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    agent_id = cb.data.split(":", 1)[1]
    await state.update_data(agent_id=agent_id)
    await state.set_state(InjectPromptForm.text)
    await cb.message.answer(
        "📨 <b>Inject Prompt</b>\n\nType the text to inject into the running agent:",
        parse_mode="HTML",
        reply_markup=keyboards.cancel_keyboard(),
    )
    await cb.answer()


@router.message(InjectPromptForm.text)
async def ip_text(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    data = await state.get_data()
    await state.clear()
    ok = await orchestrator.inject_prompt(data["agent_id"], msg.text.strip())
    await msg.answer("📨 Prompt injected." if ok else "Agent is not running.")


# ── Clone agent ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("agent_clone:"))
async def cb_agent_clone(cb: CallbackQuery, state: FSMContext) -> None:
    agent_id = cb.data.split(":", 1)[1]
    agents = await orchestrator.list_agents()
    match = next((a for a in agents if a["id"] == agent_id), None)
    name = match["name"] if match else agent_id[:8]
    await state.update_data(source_id=agent_id)
    await state.set_state(CloneAgentForm.new_name)
    await cb.message.answer(
        f"📋 <b>Clone Agent</b>\n\nCloning <b>{name}</b>.\n\nEnter a name for the clone:",
        parse_mode="HTML",
        reply_markup=keyboards.cancel_keyboard(),
    )
    await cb.answer()


@router.message(CloneAgentForm.new_name)
async def clone_name(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    data = await state.get_data()
    new_name = msg.text.strip()
    clone = await orchestrator.clone_agent(data["source_id"], new_name)
    await state.clear()
    if clone:
        await msg.answer(
            f"✅ <b>Agent cloned!</b>\n\n🤖 <b>{clone.name}</b>\nID: <code>{clone.agent_id[:8]}</code>",
            parse_mode="HTML",
            reply_markup=keyboards.agent_detail_keyboard(clone.agent_id, "idle"),
        )
    else:
        await msg.answer("❌ Clone failed - source agent not found.", reply_markup=keyboards.back_to_menu())


# ── Edit system prompt ─────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("agent_sysprompt:"))
async def cb_agent_sysprompt(cb: CallbackQuery, state: FSMContext) -> None:
    agent_id = cb.data.split(":", 1)[1]
    agents = await orchestrator.list_agents()
    match = next((a for a in agents if a["id"] == agent_id), None)
    current = match["system_prompt"][:300] if match else ""
    await state.update_data(agent_id=agent_id)
    await state.set_state(EditSysPromptForm.system_prompt)
    await cb.message.answer(
        f"📝 <b>Edit System Prompt</b>\n\n"
        f"Current (first 300 chars):\n<code>{current}</code>\n\n"
        "Send the new system prompt (or Cancel):",
        parse_mode="HTML",
        reply_markup=keyboards.cancel_keyboard(),
    )
    await cb.answer()


@router.message(EditSysPromptForm.system_prompt)
async def esp_text(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    data = await state.get_data()
    agent_id = data["agent_id"]
    await orchestrator.update_agent_system_prompt(agent_id, msg.text.strip())
    await state.clear()
    await msg.answer(
        "✅ System prompt updated.",
        reply_markup=keyboards.agent_detail_keyboard(agent_id, "idle"),
    )


# ── Agent settings ─────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("agent_settings:"))
async def cb_agent_settings(cb: CallbackQuery) -> None:
    agent_id = cb.data.split(":", 1)[1]
    row = await db.fetchone("SELECT settings FROM agents WHERE id=?", (agent_id,))
    settings = {}
    if row and row["settings"]:
        try:
            settings = json.loads(row["settings"])
        except Exception:
            pass
    await cb.message.edit_text(
        f"⚙️ <b>Agent Settings</b>\n\n"
        f"Adjust Claude CLI flags for this agent.\n"
        f"Changes take effect on the next run.",
        parse_mode="HTML",
        reply_markup=keyboards.agent_settings_keyboard(agent_id, settings),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("agt_set_toggle_skip:"))
async def cb_toggle_skip(cb: CallbackQuery) -> None:
    agent_id = cb.data.split(":", 1)[1]
    settings = await _load_agent_settings(agent_id)
    settings["skip_permissions"] = not settings.get("skip_permissions", False)
    await orchestrator.update_agent_settings(agent_id, settings)
    await cb.message.edit_reply_markup(
        reply_markup=keyboards.agent_settings_keyboard(agent_id, settings)
    )
    state_str = "ON" if settings["skip_permissions"] else "OFF"
    await cb.answer(f"Skip permissions: {state_str}")


@router.callback_query(F.data.startswith("agt_set_stream:"))
async def cb_toggle_stream(cb: CallbackQuery) -> None:
    agent_id = cb.data.split(":", 1)[1]
    settings = await _load_agent_settings(agent_id)
    modes = ["full", "tools", "silent"]
    current = settings.get("stream_mode", "full")
    next_mode = modes[(modes.index(current) + 1) % len(modes)]
    settings["stream_mode"] = next_mode
    await orchestrator.update_agent_settings(agent_id, settings)
    await cb.message.edit_reply_markup(
        reply_markup=keyboards.agent_settings_keyboard(agent_id, settings)
    )
    labels = {"full": "🔊 Full - stream everything", "tools": "🔧 Tools only - no text", "silent": "🔇 Silent - just final status"}
    await cb.answer(labels[next_mode])


@router.callback_query(F.data.startswith("agt_set_effort:"))
async def cb_set_effort(cb: CallbackQuery) -> None:
    agent_id = cb.data.split(":", 1)[1]
    await cb.message.edit_reply_markup(
        reply_markup=keyboards.effort_keyboard(agent_id)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("agt_effort:"))
async def cb_effort_pick(cb: CallbackQuery) -> None:
    _, agent_id, level = cb.data.split(":", 2)
    settings = await _load_agent_settings(agent_id)
    settings["effort"] = None if level == "default" else level
    await orchestrator.update_agent_settings(agent_id, settings)
    await cb.message.edit_reply_markup(
        reply_markup=keyboards.agent_settings_keyboard(agent_id, settings)
    )
    await cb.answer(f"Effort set to {level}")


@router.callback_query(F.data.startswith("agt_set_model:"))
async def cb_set_model(cb: CallbackQuery, state: FSMContext) -> None:
    agent_id = cb.data.split(":", 1)[1]
    settings = await _load_agent_settings(agent_id)
    await state.update_data(agent_id=agent_id, field="model", settings=settings)
    await state.set_state(AgentSettingForm.value)
    current = settings.get("model") or "default"
    await cb.message.answer(
        f"🤖 <b>Set Model</b>\n\nCurrent: <code>{current}</code>\n\n"
        "Examples: <code>claude-opus-4-8</code>, <code>claude-sonnet-4-6</code>, <code>claude-haiku-4-5-20251001</code>\n\n"
        "Send model name, or <code>default</code> to reset:",
        parse_mode="HTML",
        reply_markup=keyboards.cancel_keyboard(),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("agt_set_budget:"))
async def cb_set_budget(cb: CallbackQuery, state: FSMContext) -> None:
    agent_id = cb.data.split(":", 1)[1]
    settings = await _load_agent_settings(agent_id)
    await state.update_data(agent_id=agent_id, field="max_budget_usd", settings=settings)
    await state.set_state(AgentSettingForm.value)
    current = settings.get("max_budget_usd")
    await cb.message.answer(
        f"💰 <b>Set Budget Cap</b>\n\nCurrent: <code>{f'${current}' if current else 'none'}</code>\n\n"
        "Send a number (USD), or <code>none</code> to remove limit:",
        parse_mode="HTML",
        reply_markup=keyboards.cancel_keyboard(),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("agt_set_timeout:"))
async def cb_set_timeout(cb: CallbackQuery, state: FSMContext) -> None:
    agent_id = cb.data.split(":", 1)[1]
    settings = await _load_agent_settings(agent_id)
    await state.update_data(agent_id=agent_id, field="timeout_seconds", settings=settings)
    await state.set_state(AgentSettingForm.value)
    current = settings.get("timeout_seconds")
    await cb.message.answer(
        f"⏱ <b>Set Timeout</b>\n\nCurrent: <code>{f'{current}s' if current else 'none'}</code>\n\n"
        "Send seconds (e.g. <code>300</code>), or <code>none</code> to disable:",
        parse_mode="HTML",
        reply_markup=keyboards.cancel_keyboard(),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("agt_set_tools:"))
async def cb_set_tools(cb: CallbackQuery, state: FSMContext) -> None:
    agent_id = cb.data.split(":", 1)[1]
    settings = await _load_agent_settings(agent_id)
    await state.update_data(agent_id=agent_id, field="allowed_tools", settings=settings)
    await state.set_state(AgentSettingForm.value)
    current = settings.get("allowed_tools") or "all"
    await cb.message.answer(
        f"🛠 <b>Allowed Tools</b>\n\nCurrent: <code>{current}</code>\n\n"
        "Comma-separated list, e.g. <code>Bash,Read,Edit</code>\n"
        "Or <code>all</code> to allow everything:",
        parse_mode="HTML",
        reply_markup=keyboards.cancel_keyboard(),
    )
    await cb.answer()


@router.message(AgentSettingForm.value)
async def agt_setting_value(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    data = await state.get_data()
    agent_id = data["agent_id"]
    field = data["field"]
    settings = data.get("settings") or {}
    raw = msg.text.strip()

    if raw.lower() in ("none", "default", ""):
        settings[field] = None
    elif field in ("max_budget_usd", "timeout_seconds"):
        try:
            settings[field] = float(raw) if field == "max_budget_usd" else int(raw)
        except ValueError:
            await msg.answer(f"Invalid number: <code>{raw}</code>", parse_mode="HTML")
            return
    elif field == "allowed_tools" and raw.lower() == "all":
        settings[field] = None
    else:
        settings[field] = raw

    await orchestrator.update_agent_settings(agent_id, settings)
    await state.clear()
    await msg.answer(
        f"✅ <b>{field}</b> updated.",
        parse_mode="HTML",
        reply_markup=keyboards.agent_settings_keyboard(agent_id, settings),
    )


async def _load_agent_settings(agent_id: str) -> dict:
    row = await db.fetchone("SELECT settings FROM agents WHERE id=?", (agent_id,))
    if row and row["settings"]:
        try:
            return json.loads(row["settings"])
        except Exception:
            pass
    return {}


# ── Delete with confirm ────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("agent_delete_confirm:"))
async def cb_agent_delete_confirm(cb: CallbackQuery) -> None:
    agent_id = cb.data.split(":", 1)[1]
    agents = await orchestrator.list_agents()
    match = next((a for a in agents if a["id"] == agent_id), None)
    name = match["name"] if match else agent_id[:8]
    await cb.message.edit_text(
        f"⚠️ Delete agent <b>{name}</b>?\n\nThis will remove the agent and all its session history.",
        parse_mode="HTML",
        reply_markup=keyboards.agent_delete_confirm_keyboard(agent_id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("agent_delete:"))
async def cb_agent_delete(cb: CallbackQuery) -> None:
    agent_id = cb.data.split(":", 1)[1]
    await orchestrator.delete_agent(agent_id)
    await cb.message.edit_text("🗑 Agent deleted.", reply_markup=keyboards.back_to_menu())
    await cb.answer("Deleted.")


@router.callback_query(F.data.startswith("agent_stop:"))
async def cb_agent_stop(cb: CallbackQuery) -> None:
    agent_id = cb.data.split(":", 1)[1]
    await orchestrator.stop_agent(agent_id)
    await cb.answer("Agent stopped.")
    agents = await orchestrator.list_agents()
    match = next((a for a in agents if a["id"] == agent_id), None)
    if match:
        await cb.message.edit_text(_agent_card(match), parse_mode="HTML",
                                   reply_markup=keyboards.agent_detail_keyboard(match["id"], match["status"]))


@router.callback_query(F.data.startswith("agent_kill:"))
async def cb_agent_kill(cb: CallbackQuery) -> None:
    agent_id = cb.data.split(":", 1)[1]
    await orchestrator.kill_agent(agent_id)
    await cb.answer("Agent killed.")
    agents = await orchestrator.list_agents()
    match = next((a for a in agents if a["id"] == agent_id), None)
    if match:
        await cb.message.edit_text(_agent_card(match), parse_mode="HTML",
                                   reply_markup=keyboards.agent_detail_keyboard(match["id"], match["status"]))


# ── Template detail ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("tpl_detail:"))
async def cb_tpl_detail(cb: CallbackQuery) -> None:
    name = cb.data.split(":", 1)[1]
    row = await db.fetchone("SELECT * FROM templates WHERE name = ?", (name,))
    if not row:
        await cb.answer("Template not found.", show_alert=True)
        return
    tag = "⭐ built-in" if row["is_builtin"] else "✏️ custom"
    await cb.message.edit_text(
        f"<b>📋 {row['name']}</b> [{tag}]\n\n"
        f"<i>{row['description'] or ''}</i>\n\n"
        f"<b>System Prompt:</b>\n<pre>{row['system_prompt'][:800]}</pre>",
        parse_mode="HTML",
        reply_markup=keyboards.template_detail_keyboard(name),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("tpl_use:"))
async def cb_tpl_use(cb: CallbackQuery, state: FSMContext) -> None:
    tpl_name = cb.data.split(":", 1)[1]
    row = await db.fetchone("SELECT * FROM templates WHERE name = ?", (tpl_name,))
    if not row:
        await cb.answer("Template not found.", show_alert=True)
        return
    await state.update_data(template=tpl_name, system_prompt=row["system_prompt"])
    await state.set_state(NewAgentForm.name)
    await cb.message.answer(
        f"🤖 <b>New Agent</b> using <b>{tpl_name}</b> template\n\nStep 1 - What should the agent be <b>named</b>?",
        parse_mode="HTML",
        reply_markup=keyboards.cancel_keyboard(),
    )
    await cb.answer()


# ── Rename agent ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("agent_rename:"))
async def cb_agent_rename(cb: CallbackQuery, state: FSMContext) -> None:
    agent_id = cb.data.split(":", 1)[1]
    await state.update_data(agent_id=agent_id)
    await state.set_state(RenameAgentForm.new_name)
    agents = await orchestrator.list_agents()
    match = next((a for a in agents if a["id"] == agent_id), None)
    current = match["name"] if match else "?"
    await cb.message.answer(
        f"✏️ <b>Rename Agent</b>\n\nCurrent name: <b>{current}</b>\n\nEnter the new name:",
        parse_mode="HTML",
        reply_markup=keyboards.cancel_keyboard(),
    )
    await cb.answer()


@router.message(RenameAgentForm.new_name)
async def ra_new_name(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    data = await state.get_data()
    agent_id = data["agent_id"]
    new_name = msg.text.strip()
    await db.execute("UPDATE agents SET name=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (new_name, agent_id))
    await state.clear()
    agents = await orchestrator.list_agents()
    match = next((a for a in agents if a["id"] == agent_id), None)
    await msg.answer(
        f"✅ Agent renamed to <b>{new_name}</b>.",
        parse_mode="HTML",
        reply_markup=keyboards.agent_detail_keyboard(agent_id, match["status"] if match else "idle"),
    )


@router.message(Command("rename_agent"))
async def cmd_rename_agent(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await msg.answer("Usage: /rename_agent <id> <new_name>")
        return
    match = await _find_agent(parts[1])
    if not match:
        await msg.answer("Agent not found.")
        return
    new_name = parts[2].strip()
    await db.execute("UPDATE agents SET name=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (new_name, match["id"]))
    await msg.answer(f"✅ Renamed to <b>{new_name}</b>.", parse_mode="HTML")


# ── /status command ────────────────────────────────────────────────────────

@router.message(Command("status"))
async def cmd_status(msg: Message) -> None:
    from core import bridge as bridge_mod, approval as appr
    agents = await orchestrator.list_agents()
    stats  = await orchestrator.agent_stats()
    groups = await bridge_mod.list_groups()
    pending = await appr.get_pending_requests()
    lines = ["<b>📊 SOPHIA Status</b>\n"]
    lines.append(f"<b>Agents ({len(agents)})</b>")
    for a in agents:
        rc   = a["run_count"] if "run_count" in a.keys() else 0
        last = str(a["last_run_at"])[:16] if a["last_run_at"] else "never"
        lines.append(
            f"  {STATUS_ICON.get(a['status'], '❓')} <b>{a['name']}</b> [{a['role']}] "
            f"- {a['status']}  runs:{rc}  last:{last}"
        )
    if not agents:
        lines.append("  None yet")
    lines.append(f"\n<b>Groups ({len(groups)})</b>")
    for g in groups:
        lines.append(f"  🔗 {g['name']} [{g['bridge_mode']}]")
    if not groups:
        lines.append("  None yet")
    lines.append(f"\n<b>Pending Approvals ({len(pending)})</b>")
    for p in pending:
        lines.append(f"  ⚠️ #{p['id']} {p['agent_name']}: {p['prompt'][:60]}…")
    if not pending:
        lines.append("  None")
    await msg.answer("\n".join(lines), parse_mode="HTML",
                     reply_markup=keyboards.main_menu_keyboard())


# ── Text-based start/stop/kill/delete/prompt commands ─────────────────────

@router.message(Command("start_agent"))
async def cmd_start_agent(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await msg.answer("Usage: /start_agent <id> <prompt>")
        return
    match = await _find_agent(parts[1])
    if not match:
        await msg.answer("Agent not found.")
        return
    ok = await orchestrator.start_agent(match["id"], parts[2], msg.chat.id)
    if ok:
        await msg.answer(f"🚀 <b>{match['name']}</b> started.", parse_mode="HTML")
    else:
        await msg.answer("Failed to start (already running or agent missing).")


@router.message(Command("stop_agent"))
async def cmd_stop_agent(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Usage: /stop_agent <id>")
        return
    match = await _find_agent(parts[1].strip())
    if not match:
        await msg.answer("Agent not found.")
        return
    await orchestrator.stop_agent(match["id"])
    await msg.answer(f"⏹ <b>{match['name']}</b> stopped.", parse_mode="HTML")


@router.message(Command("kill_agent"))
async def cmd_kill_agent(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Usage: /kill_agent <id>")
        return
    match = await _find_agent(parts[1].strip())
    if not match:
        await msg.answer("Agent not found.")
        return
    await orchestrator.kill_agent(match["id"])
    await msg.answer(f"💀 <b>{match['name']}</b> killed.", parse_mode="HTML")


@router.message(Command("delete_agent"))
async def cmd_delete_agent(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Usage: /delete_agent <id>")
        return
    match = await _find_agent(parts[1].strip())
    if not match:
        await msg.answer("Agent not found.")
        return
    await orchestrator.delete_agent(match["id"])
    await msg.answer(f"🗑 <b>{match['name']}</b> deleted.", parse_mode="HTML",
                     reply_markup=keyboards.back_to_menu())


@router.message(Command("prompt"))
async def cmd_prompt(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await msg.answer("Usage: /prompt <id> <text>")
        return
    match = await _find_agent(parts[1])
    if not match:
        await msg.answer("Agent not found.")
        return
    ok = await orchestrator.inject_prompt(match["id"], parts[2])
    if ok:
        await msg.answer(f"📨 Prompt injected into <b>{match['name']}</b>.", parse_mode="HTML")
    else:
        await msg.answer("Agent is not running.")


# ── Helpers ────────────────────────────────────────────────────────────────

async def _find_agent(id_prefix: str):
    agents = await orchestrator.list_agents()
    return next(
        (a for a in agents if a["id"].startswith(id_prefix) or a["name"] == id_prefix),
        None,
    )
