import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from core import workspace as ws_mod
from bot import keyboards

log = logging.getLogger(__name__)
router = Router()


class NewWorkspaceForm(StatesGroup):
    name        = State()
    path        = State()
    runner_type = State()
    ssh_host    = State()


class EditWorkspacePathForm(StatesGroup):
    ws_id = State()
    path  = State()


@router.message(Command("workspaces"))
async def cmd_workspaces(msg: Message) -> None:
    ws_list = await ws_mod.list_workspaces()
    if not ws_list:
        await msg.answer(
            "<b>📁 Workspaces</b>\n\nNo workspaces yet. Add one to point agents at a project.",
            parse_mode="HTML",
            reply_markup=keyboards.workspaces_list_keyboard([]),
        )
        return
    lines = ["<b>📁 Workspaces</b>\n"]
    for w in ws_list:
        icon = "💻" if w["runner_type"] == "local" else "🌐"
        ssh_tag = f" via {w['ssh_alias']}" if w["ssh_alias"] else ""
        lines.append(f"{icon} <b>{w['name']}</b>{ssh_tag}\n   <code>{w['path']}</code>")
    lines.append("\n<i>Tap a workspace to manage it.</i>")
    await msg.answer("\n".join(lines), parse_mode="HTML",
                     reply_markup=keyboards.workspaces_list_keyboard(ws_list))


@router.callback_query(F.data.startswith("ws_detail:"))
async def cb_ws_detail(cb: CallbackQuery) -> None:
    ws_id = int(cb.data.split(":", 1)[1])
    w = await ws_mod.get_workspace(ws_id)
    if not w:
        await cb.answer("Workspace not found.", show_alert=True)
        return
    icon = "💻" if w["runner_type"] == "local" else "🌐"
    text = (
        f"<b>{icon} {w['name']}</b>\n\n"
        f"Path:    <code>{w['path']}</code>\n"
        f"Runner:  {w['runner_type']}\n"
        f"Created: {str(w['created_at'])[:16]}"
    )
    import os
    path_ok = os.path.isdir(w["path"]) if w["runner_type"] == "local" else True
    warning = "" if path_ok else "\n⚠️ <b>Path does not exist on disk!</b> Tap Edit Path to fix it."
    await cb.message.edit_text(text + warning, parse_mode="HTML",
                               reply_markup=keyboards.workspace_detail_keyboard(ws_id))
    await cb.answer()


@router.callback_query(F.data.startswith("ws_edit_path:"))
async def cb_ws_edit_path(cb: CallbackQuery, state: FSMContext) -> None:
    ws_id = int(cb.data.split(":", 1)[1])
    w = await ws_mod.get_workspace(ws_id)
    await state.update_data(ws_id=ws_id)
    await state.set_state(EditWorkspacePathForm.path)
    await cb.message.answer(
        f"📁 Enter the new absolute path for <b>{w['name'] if w else ws_id}</b>:\n\n"
        f"Current: <code>{w['path'] if w else '?'}</code>\n\n"
        f"Example: <code>/home/user/myproject</code>",
        parse_mode="HTML",
        reply_markup=keyboards.cancel_keyboard(),
    )
    await cb.answer()


@router.message(EditWorkspacePathForm.path)
async def ewp_path(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    new_path = msg.text.strip()
    if not new_path.startswith("/"):
        await msg.answer("⚠️ Path must be absolute (start with <code>/</code>).", parse_mode="HTML")
        return
    data = await state.get_data()
    ws_id = data["ws_id"]
    await ws_mod.update_workspace_path(ws_id, new_path)
    await state.clear()
    import os
    exists = os.path.isdir(new_path)
    note = "✅ Path exists on disk." if exists else "⚠️ Path does not exist yet - make sure to create it before running an agent."
    await msg.answer(
        f"✅ <b>Workspace path updated!</b>\n\n<code>{new_path}</code>\n\n{note}",
        parse_mode="HTML",
        reply_markup=keyboards.workspaces_list_keyboard(await ws_mod.list_workspaces()),
    )


@router.callback_query(F.data.startswith("ws_delete_confirm:"))
async def cb_ws_delete_confirm(cb: CallbackQuery) -> None:
    ws_id = int(cb.data.split(":", 1)[1])
    w = await ws_mod.get_workspace(ws_id)
    name = w["name"] if w else f"#{ws_id}"
    await cb.message.edit_text(
        f"⚠️ Delete workspace <b>{name}</b>?",
        parse_mode="HTML",
        reply_markup=keyboards.ws_delete_confirm_keyboard(ws_id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("ws_delete:"))
async def cb_ws_delete(cb: CallbackQuery) -> None:
    ws_id = int(cb.data.split(":", 1)[1])
    await ws_mod.delete_workspace(ws_id)
    await cb.message.edit_text("🗑 Workspace deleted.", reply_markup=keyboards.back_to_menu())
    await cb.answer("Deleted.")


@router.message(Command("new_workspace"))
async def cmd_new_workspace(msg: Message, state: FSMContext) -> None:
    await state.set_state(NewWorkspaceForm.name)
    await msg.answer(
        "📁 <b>New Workspace</b> - Step 1/3\n\nEnter a <b>name</b> for this workspace:",
        parse_mode="HTML",
        reply_markup=keyboards.cancel_keyboard(),
    )


@router.message(NewWorkspaceForm.name)
async def nw_name(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    await state.update_data(name=msg.text.strip())
    await msg.answer(
        "📁 <b>New Workspace</b> - Step 2/3\n\n"
        "Enter the <b>absolute path</b> to the project directory.\n\n"
        "Examples:\n<code>/home/user/myproject</code>\n<code>/opt/api</code>",
        parse_mode="HTML",
    )
    await state.set_state(NewWorkspaceForm.path)


@router.message(NewWorkspaceForm.path)
async def nw_path(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    path = msg.text.strip()
    if not path.startswith("/"):
        await msg.answer(
            "⚠️ Please enter an <b>absolute path</b> starting with <code>/</code>\n\n"
            "Example: <code>/home/user/myproject</code>",
            parse_mode="HTML",
        )
        return
    await state.update_data(path=path)
    await msg.answer(
        "📁 <b>New Workspace</b> - Step 3/3\n\nSelect the runner type:",
        parse_mode="HTML",
        reply_markup=keyboards.runner_keyboard(),
    )
    await state.set_state(NewWorkspaceForm.runner_type)


@router.callback_query(F.data.startswith("runner:"), NewWorkspaceForm.runner_type)
async def nw_runner(cb: CallbackQuery, state: FSMContext) -> None:
    runner_type = cb.data.split(":", 1)[1]
    await state.update_data(runner_type=runner_type)

    if runner_type == "ssh":
        hosts = await ws_mod.list_ssh_hosts()
        if not hosts:
            await cb.message.edit_text(
                "⚠️ No SSH hosts configured yet.\n\nAdd one first with /new_ssh_host or the SSH Hosts menu.",
                reply_markup=keyboards.back_to_menu(),
            )
            await state.clear()
            await cb.answer()
            return
        lines = ["<b>Select SSH host</b> - reply with the host ID:\n"]
        for h in hosts:
            lines.append(f"  <b>#{h['id']}</b> {h['alias']}  {h['username']}@{h['host']}:{h['port']}")
        await cb.message.edit_text("\n".join(lines), parse_mode="HTML",
                                   reply_markup=keyboards.cancel_keyboard())
        await state.set_state(NewWorkspaceForm.ssh_host)
        await cb.answer()
        return

    data = await state.get_data()
    wid = await ws_mod.create_workspace(data["name"], data["path"], "local")
    await cb.message.edit_text(
        f"✅ <b>Workspace created!</b>\n\n"
        f"💻 <b>{data['name']}</b>\n"
        f"Path: <code>{data['path']}</code>\n"
        f"ID: #{wid}",
        parse_mode="HTML",
        reply_markup=keyboards.workspaces_list_keyboard(await ws_mod.list_workspaces()),
    )
    await state.clear()
    await cb.answer()


@router.message(NewWorkspaceForm.ssh_host)
async def nw_ssh_host(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    try:
        host_id = int(msg.text.strip().lstrip("#"))
    except ValueError:
        await msg.answer("Please enter a valid SSH host ID number.")
        return
    host = await ws_mod.get_ssh_host(host_id)
    if not host:
        await msg.answer("SSH host not found.")
        return
    data = await state.get_data()
    wid = await ws_mod.create_workspace(data["name"], data["path"], "ssh", host_id)
    await msg.answer(
        f"✅ <b>Workspace created!</b>\n\n"
        f"🌐 <b>{data['name']}</b> via {host['alias']}\n"
        f"Path: <code>{data['path']}</code>\n"
        f"ID: #{wid}",
        parse_mode="HTML",
        reply_markup=keyboards.workspaces_list_keyboard(await ws_mod.list_workspaces()),
    )
    await state.clear()


@router.message(Command("delete_workspace"))
async def cmd_delete_workspace(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Usage: /delete_workspace <id>")
        return
    try:
        wid = int(parts[1])
    except ValueError:
        await msg.answer("ID must be a number.")
        return
    ok = await ws_mod.delete_workspace(wid)
    await msg.answer(f"🗑 Workspace #{wid} deleted." if ok else "Workspace not found.")
