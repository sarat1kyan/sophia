import logging
from aiogram import Bot, Dispatcher, Router, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, BotCommand
from aiogram.filters import Command

from bot.auth import AuthMiddleware
from bot import keyboards
from bot.handlers import agents, sessions, approvals, workspace, ssh, admin, groups, templates, sophia

log = logging.getLogger(__name__)


async def setup_commands(bot: Bot) -> None:
    commands = [
        BotCommand(command="start",          description="Home dashboard"),
        BotCommand(command="help",           description="Full command reference"),
        BotCommand(command="status",         description="Live dashboard"),
        BotCommand(command="ping",           description="Health check & uptime"),
        BotCommand(command="agents",         description="Manage agents"),
        BotCommand(command="new_agent",      description="Create new agent"),
        BotCommand(command="run",            description="Quick start: /run <name> <task>"),
        BotCommand(command="groups",         description="Agent groups"),
        BotCommand(command="sessions",       description="Session history"),
        BotCommand(command="workspaces",     description="Project workspaces"),
        BotCommand(command="ssh_hosts",      description="SSH host connections"),
        BotCommand(command="templates",      description="Role templates"),
        BotCommand(command="pending",        description="Pending approvals"),
        BotCommand(command="logs",           description="Tail system log"),
        BotCommand(command="sophia",          description="Ask Sophia to orchestrate a project"),
        BotCommand(command="stop_all",       description="Stop all running agents"),
        BotCommand(command="kill_all",       description="Kill all running agents"),
    ]
    await bot.set_my_commands(commands)


def create_bot(token: str) -> Bot:
    return Bot(token=token)


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(AuthMiddleware())

    dp.include_router(_base_router())
    dp.include_router(agents.router)
    dp.include_router(sessions.router)
    dp.include_router(approvals.router)
    dp.include_router(workspace.router)
    dp.include_router(ssh.router)
    dp.include_router(admin.router)
    dp.include_router(groups.router)
    dp.include_router(templates.router)
    dp.include_router(sophia.router)
    return dp


def _base_router() -> Router:
    r = Router()

    @r.message(Command("start"))
    async def cmd_start(msg: Message) -> None:
        from core import orchestrator, approval as appr
        agents_list  = await orchestrator.list_agents()
        pending      = await appr.get_pending_requests()
        running      = sum(1 for a in agents_list if a["status"] == "running")
        total        = len(agents_list)
        pending_n    = len(pending)

        alert = f"  ⚠️ {pending_n} pending approval{'s' if pending_n != 1 else ''}\n" if pending_n else ""

        await msg.answer(
            f"<b>SOPHIA</b> - Claude Code Agent Orchestrator\n\n"
            f"🤖 Agents: <b>{total}</b>  ({running} running)\n"
            f"⏳ Pending: <b>{pending_n}</b>\n"
            f"{alert}\n"
            f"Use the menu below or type any /command.",
            parse_mode="HTML",
            reply_markup=keyboards.main_menu_keyboard(),
        )

    @r.message(Command("help"))
    async def cmd_help(msg: Message) -> None:
        await msg.answer(
            "<b>SOPHIA - Command Reference</b>\n\n"
            "<b>Agents</b>\n"
            "/new_agent - create agent (wizard)\n"
            "/agents - list all agents\n"
            "/agent &lt;id&gt; - agent detail\n"
            "/run &lt;name&gt; &lt;task&gt; - quick start\n"
            "/start_agent &lt;id&gt; &lt;prompt&gt;\n"
            "/stop_agent &lt;id&gt; · /kill_agent &lt;id&gt;\n"
            "/rename_agent &lt;id&gt; &lt;name&gt;\n"
            "/delete_agent &lt;id&gt; · /prompt &lt;id&gt; &lt;text&gt;\n"
            "/status · /ping\n\n"
            "<b>Groups</b>\n"
            "/new_group · /groups · /group &lt;id&gt;\n"
            "/add_to_group &lt;gid&gt; &lt;aid&gt;\n"
            "/remove_from_group · /dissolve_group &lt;id&gt;\n\n"
            "<b>Sessions</b>\n"
            "/sessions · /session &lt;id&gt;\n"
            "/clear_session &lt;id&gt; · /export_session &lt;id&gt;\n\n"
            "<b>Workspaces</b>\n"
            "/workspaces · /new_workspace · /delete_workspace &lt;id&gt;\n\n"
            "<b>SSH Hosts</b>\n"
            "/ssh_hosts · /new_ssh_host · /test_ssh &lt;id&gt;\n"
            "/delete_ssh_host &lt;id&gt;\n\n"
            "<b>Approvals</b>\n"
            "/pending · /approve &lt;id&gt; · /deny &lt;id&gt;\n\n"
            "<b>Templates</b>\n"
            "/templates · /template &lt;name&gt; · /new_template\n\n"
            "<b>Sophia - Orchestrator</b>\n"
            "/sophia - ask Sophia to build a project (auto-creates workspace + agents)\n\n"
            "<b>Admin</b>\n"
            "/add_user · /remove_user · /users\n"
            "/logs · /restart · /config\n"
            "/stop_all · /kill_all",
            parse_mode="HTML",
            reply_markup=keyboards.main_menu_keyboard(),
        )

    # ── Menu callback dispatch ─────────────────────────────────────────────

    @r.callback_query(F.data == "menu:home")
    async def cb_menu_home(cb: CallbackQuery) -> None:
        from core import orchestrator, approval as appr
        agents_list = await orchestrator.list_agents()
        pending     = await appr.get_pending_requests()
        running     = sum(1 for a in agents_list if a["status"] == "running")
        total       = len(agents_list)
        pending_n   = len(pending)
        alert = f"  ⚠️ {pending_n} pending approval{'s' if pending_n != 1 else ''}\n" if pending_n else ""
        await cb.message.edit_text(
            f"<b>SOPHIA</b> - Claude Code Agent Orchestrator\n\n"
            f"🤖 Agents: <b>{total}</b>  ({running} running)\n"
            f"⏳ Pending: <b>{pending_n}</b>\n"
            f"{alert}\n"
            f"Use the menu below or type any /command.",
            parse_mode="HTML",
            reply_markup=keyboards.main_menu_keyboard(),
        )
        await cb.answer()

    @r.callback_query(F.data == "menu:agents")
    async def cb_menu_agents(cb: CallbackQuery) -> None:
        from core import orchestrator
        STATUS_ICON = {"idle": "💤", "running": "🟢", "done": "✅", "error": "🔴", "waiting_approval": "⏳"}
        agents_list = await orchestrator.list_agents()
        if not agents_list:
            await cb.message.edit_text(
                "<b>🤖 Agents</b>\n\nNo agents yet.\nCreate your first agent to get started.",
                parse_mode="HTML",
                reply_markup=keyboards.agents_list_keyboard([]),
            )
            await cb.answer()
            return
        lines = ["<b>🤖 Agents</b>\n"]
        for a in agents_list:
            icon = STATUS_ICON.get(a["status"], "❓")
            ws = f"  📁 {a['workspace_name']}" if a["workspace_name"] else ""
            rc = a["run_count"] if "run_count" in a.keys() else 0
            lines.append(f"{icon} <b>{a['name']}</b> [{a['role']}]{ws}  <i>×{rc}</i>")
        lines.append("\n<i>Tap an agent to manage it.</i>")
        await cb.message.edit_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=keyboards.agents_list_keyboard(agents_list),
        )
        await cb.answer()

    @r.callback_query(F.data == "menu:groups")
    async def cb_menu_groups(cb: CallbackQuery) -> None:
        from core import bridge as bridge_mod
        groups_list = await bridge_mod.list_groups()
        if not groups_list:
            text = "<b>👥 Groups</b>\n\nNo groups yet. Create one to link agents together."
        else:
            lines = ["<b>👥 Groups</b>\n"]
            for g in groups_list:
                icon = "📡" if g["bridge_mode"] == "broadcast" else "👑"
                lines.append(f"{icon} <b>{g['name']}</b> [{g['bridge_mode']}]")
            lines.append("\n<i>Tap a group to manage it.</i>")
            text = "\n".join(lines)
        await cb.message.edit_text(text, parse_mode="HTML",
                                   reply_markup=keyboards.groups_list_keyboard(groups_list))
        await cb.answer()

    @r.callback_query(F.data == "menu:workspaces")
    async def cb_menu_workspaces(cb: CallbackQuery) -> None:
        from core import workspace as ws_mod
        ws_list = await ws_mod.list_workspaces()
        if not ws_list:
            text = "<b>📁 Workspaces</b>\n\nNo workspaces yet. Add one to point agents at a project directory."
        else:
            lines = ["<b>📁 Workspaces</b>\n"]
            for w in ws_list:
                icon = "💻" if w["runner_type"] == "local" else "🌐"
                ssh_tag = f" via {w['ssh_alias']}" if w["ssh_alias"] else ""
                lines.append(f"{icon} <b>{w['name']}</b>{ssh_tag}\n   <code>{w['path']}</code>")
            lines.append("\n<i>Tap a workspace to manage it.</i>")
            text = "\n".join(lines)
        await cb.message.edit_text(text, parse_mode="HTML",
                                   reply_markup=keyboards.workspaces_list_keyboard(ws_list))
        await cb.answer()

    @r.callback_query(F.data == "menu:ssh")
    async def cb_menu_ssh(cb: CallbackQuery) -> None:
        from core import workspace as ws_mod
        hosts = await ws_mod.list_ssh_hosts()
        if not hosts:
            text = "<b>🌐 SSH Hosts</b>\n\nNo SSH hosts configured. Add one to run agents on remote machines."
        else:
            lines = ["<b>🌐 SSH Hosts</b>\n"]
            for h in hosts:
                auth = "🔑 key" if h["key_path"] else "🔐 password"
                lines.append(f"🖧 <b>{h['alias']}</b> - {h['username']}@{h['host']}:{h['port']} [{auth}]")
            lines.append("\n<i>Tap a host to test or delete it.</i>")
            text = "\n".join(lines)
        await cb.message.edit_text(text, parse_mode="HTML",
                                   reply_markup=keyboards.ssh_list_keyboard(hosts))
        await cb.answer()

    @r.callback_query(F.data == "menu:sessions")
    async def cb_menu_sessions(cb: CallbackQuery) -> None:
        from core import session as session_mod
        sess_list = await session_mod.list_sessions()
        if not sess_list:
            text = "<b>💬 Sessions</b>\n\nNo sessions yet. Start an agent to create a session."
        else:
            lines = ["<b>💬 Sessions</b>\n"]
            for s in sess_list:
                lines.append(f"• #{s['id']} <b>{s['agent_name'] or 'unknown'}</b> - {s['updated_at'][:16]}")
            lines.append("\n<i>Tap a session to view or export it.</i>")
            text = "\n".join(lines)
        await cb.message.edit_text(text, parse_mode="HTML",
                                   reply_markup=keyboards.sessions_list_keyboard(sess_list))
        await cb.answer()

    @r.callback_query(F.data == "menu:templates")
    async def cb_menu_templates(cb: CallbackQuery) -> None:
        from storage import db
        tpls = await db.fetchall("SELECT * FROM templates ORDER BY is_builtin DESC, name")
        lines = ["<b>📋 Role Templates</b>\n"]
        for t in tpls:
            icon = "⭐" if t["is_builtin"] else "✏️"
            lines.append(f"{icon} <b>{t['name']}</b> - {t['description'] or ''}")
        lines.append("\n<i>Tap a template to view its system prompt or use it.</i>")
        await cb.message.edit_text("\n".join(lines), parse_mode="HTML",
                                   reply_markup=keyboards.templates_list_keyboard(tpls))
        await cb.answer()

    @r.callback_query(F.data == "menu:pending")
    async def cb_menu_pending(cb: CallbackQuery) -> None:
        from core import approval as appr
        pending = await appr.get_pending_requests()
        if not pending:
            await cb.message.edit_text(
                "<b>⏳ Pending Approvals</b>\n\nNo pending requests. All clear!",
                parse_mode="HTML",
                reply_markup=keyboards.back_to_menu(),
            )
            await cb.answer()
            return
        lines = [f"<b>⏳ Pending Approvals ({len(pending)})</b>\n"]
        for p in pending:
            lines.append(
                f"• <b>#{p['id']}</b> [{p['agent_name'] or p['agent_id']}]\n"
                f"  <code>{p['prompt'][:150]}</code>\n"
                f"  Requested: {p['requested_at'][:16]}"
            )
        await cb.message.edit_text("\n".join(lines), parse_mode="HTML",
                                   reply_markup=keyboards.back_to_menu())
        await cb.answer()

    @r.callback_query(F.data == "menu:status")
    async def cb_menu_status(cb: CallbackQuery) -> None:
        from core import orchestrator, bridge as bridge_mod, approval as appr
        agents_list = await orchestrator.list_agents()
        groups_list = await bridge_mod.list_groups()
        pending     = await appr.get_pending_requests()
        STATUS_ICON = {"idle": "💤", "running": "🟢", "done": "✅", "error": "🔴", "waiting_approval": "⏳"}
        lines = ["<b>📊 SOPHIA Status</b>\n"]
        lines.append(f"<b>Agents ({len(agents_list)})</b>")
        for a in agents_list:
            rc   = a["run_count"] if "run_count" in a.keys() else 0
            last = str(a["last_run_at"])[:16] if a["last_run_at"] else "-"
            lines.append(
                f"  {STATUS_ICON.get(a['status'],'❓')} <b>{a['name']}</b> [{a['role']}]"
                f"  runs:{rc}  last:{last}"
            )
        if not agents_list:
            lines.append("  No agents yet")
        lines.append(f"\n<b>Groups ({len(groups_list)})</b>")
        for g in groups_list:
            lines.append(f"  🔗 {g['name']} [{g['bridge_mode']}]")
        if not groups_list:
            lines.append("  No groups yet")
        lines.append(f"\n<b>Pending Approvals ({len(pending)})</b>")
        for p in pending:
            lines.append(f"  ⚠️ #{p['id']} {p['agent_name']}: {p['prompt'][:60]}…")
        if not pending:
            lines.append("  None")
        await cb.message.edit_text("\n".join(lines), parse_mode="HTML",
                                   reply_markup=keyboards.main_menu_keyboard())
        await cb.answer()

    # ── Wizard entry points via buttons ───────────────────────────────────

    @r.callback_query(F.data == "wizard:new_agent")
    async def cb_wizard_new_agent(cb: CallbackQuery, state) -> None:
        from aiogram.fsm.context import FSMContext
        from bot.handlers.agents import NewAgentForm
        await state.set_state(NewAgentForm.name)
        await cb.message.answer(
            "🤖 <b>New Agent</b> - Step 1/4\n\nWhat should the agent be <b>named</b>?",
            parse_mode="HTML",
            reply_markup=keyboards.cancel_keyboard(),
        )
        await cb.answer()

    @r.callback_query(F.data == "wizard:new_workspace")
    async def cb_wizard_new_workspace(cb: CallbackQuery, state) -> None:
        from bot.handlers.workspace import NewWorkspaceForm
        await state.set_state(NewWorkspaceForm.name)
        await cb.message.answer(
            "📁 <b>New Workspace</b> - Step 1/3\n\nEnter a <b>name</b> for this workspace:",
            parse_mode="HTML",
            reply_markup=keyboards.cancel_keyboard(),
        )
        await cb.answer()

    @r.callback_query(F.data == "wizard:new_ssh")
    async def cb_wizard_new_ssh(cb: CallbackQuery, state) -> None:
        from bot.handlers.ssh import NewSSHHostForm
        await state.set_state(NewSSHHostForm.alias)
        await cb.message.answer(
            "🌐 <b>New SSH Host</b> - Step 1/5\n\nEnter an <b>alias</b> for this host:",
            parse_mode="HTML",
            reply_markup=keyboards.cancel_keyboard(),
        )
        await cb.answer()

    @r.callback_query(F.data == "wizard:new_group")
    async def cb_wizard_new_group(cb: CallbackQuery, state) -> None:
        from bot.handlers.groups import NewGroupForm
        await state.set_state(NewGroupForm.name)
        await cb.message.answer(
            "👥 <b>New Group</b> - Step 1/2\n\nEnter a <b>name</b> for this group:",
            parse_mode="HTML",
            reply_markup=keyboards.cancel_keyboard(),
        )
        await cb.answer()

    @r.callback_query(F.data == "wizard:new_template")
    async def cb_wizard_new_template(cb: CallbackQuery, state) -> None:
        from bot.handlers.templates import NewTemplateForm
        await state.set_state(NewTemplateForm.name)
        await cb.message.answer(
            "📋 <b>New Template</b> - Step 1/3\n\nEnter the template <b>name</b>:",
            parse_mode="HTML",
            reply_markup=keyboards.cancel_keyboard(),
        )
        await cb.answer()

    # ── Global cancel ──────────────────────────────────────────────────────

    @r.callback_query(F.data == "cancel")
    async def cb_cancel(cb: CallbackQuery, state) -> None:
        await state.clear()
        await cb.message.edit_text(
            "Cancelled.",
            reply_markup=keyboards.back_to_menu(),
        )
        await cb.answer()

    return r
