import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from core import bridge as bridge_mod
from core import orchestrator
from bot import keyboards
from storage import db

log = logging.getLogger(__name__)
router = Router()


class NewGroupForm(StatesGroup):
    name        = State()
    bridge_mode = State()


@router.message(Command("groups"))
async def cmd_groups(msg: Message) -> None:
    groups = await bridge_mod.list_groups()
    if not groups:
        await msg.answer(
            "<b>👥 Groups</b>\n\nNo groups yet. Create one to link agents together.",
            parse_mode="HTML",
            reply_markup=keyboards.groups_list_keyboard([]),
        )
        return
    lines = ["<b>👥 Groups</b>\n"]
    for g in groups:
        icon = "📡" if g["bridge_mode"] == "broadcast" else "👑"
        lines.append(f"{icon} <b>{g['name']}</b> [{g['bridge_mode']}]")
    lines.append("\n<i>Tap a group to manage it.</i>")
    await msg.answer("\n".join(lines), parse_mode="HTML",
                     reply_markup=keyboards.groups_list_keyboard(groups))


@router.callback_query(F.data.startswith("group_detail:"))
async def cb_group_detail(cb: CallbackQuery) -> None:
    gid = int(cb.data.split(":", 1)[1])
    group = await bridge_mod.get_group(gid)
    if not group:
        await cb.answer("Group not found.", show_alert=True)
        return
    members = await db.fetchall(
        "SELECT id, name, role, status FROM agents WHERE group_id = ?", (gid,)
    )
    icon = "📡" if group["bridge_mode"] == "broadcast" else "👑"
    STATUS_ICON = {"idle": "💤", "running": "🟢", "done": "✅", "error": "🔴"}
    lines = [
        f"<b>{icon} {group['name']}</b>\n",
        f"Mode:    {group['bridge_mode']}",
        f"Created: {str(group['created_at'])[:16]}",
        f"\n<b>Members ({len(members)})</b>",
    ]
    for a in members:
        lines.append(f"  {STATUS_ICON.get(a['status'],'❓')} {a['name']} [{a['role']}]")
    if not members:
        lines.append("  No members yet")
    lines.append(f"\n<i>Add agents with /add_to_group {gid} &lt;agent_id&gt;</i>")
    await cb.message.edit_text("\n".join(lines), parse_mode="HTML",
                               reply_markup=keyboards.group_detail_keyboard(gid))
    await cb.answer()


@router.callback_query(F.data.startswith("group_dissolve_confirm:"))
async def cb_dissolve_confirm(cb: CallbackQuery) -> None:
    gid = int(cb.data.split(":", 1)[1])
    group = await bridge_mod.get_group(gid)
    name = group["name"] if group else f"#{gid}"
    await cb.message.edit_text(
        f"⚠️ Dissolve group <b>{name}</b>?\n\nAgents will be unlinked but not deleted.",
        parse_mode="HTML",
        reply_markup=keyboards.group_dissolve_confirm_keyboard(gid),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("group_dissolve:"))
async def cb_dissolve(cb: CallbackQuery) -> None:
    gid = int(cb.data.split(":", 1)[1])
    await bridge_mod.dissolve_group(gid)
    await cb.message.edit_text("💣 Group dissolved.", reply_markup=keyboards.back_to_menu())
    await cb.answer("Dissolved.")


@router.message(Command("group"))
async def cmd_group_detail(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Usage: /group <id>")
        return
    try:
        gid = int(parts[1])
    except ValueError:
        await msg.answer("Group ID must be a number.")
        return
    group = await bridge_mod.get_group(gid)
    if not group:
        await msg.answer("Group not found.")
        return
    members = await db.fetchall("SELECT id, name, role, status FROM agents WHERE group_id = ?", (gid,))
    STATUS_ICON = {"idle": "💤", "running": "🟢", "done": "✅", "error": "🔴"}
    icon = "📡" if group["bridge_mode"] == "broadcast" else "👑"
    lines = [f"<b>{icon} {group['name']}</b>\n", f"Mode: {group['bridge_mode']}\n",
             f"<b>Members ({len(members)})</b>"]
    for a in members:
        lines.append(f"  {STATUS_ICON.get(a['status'],'❓')} {a['name']} [{a['role']}]")
    await msg.answer("\n".join(lines), parse_mode="HTML",
                     reply_markup=keyboards.group_detail_keyboard(gid))


@router.message(Command("new_group"))
async def cmd_new_group(msg: Message, state: FSMContext) -> None:
    await state.set_state(NewGroupForm.name)
    await msg.answer(
        "👥 <b>New Group</b> - Step 1/2\n\nEnter a <b>name</b> for this group:",
        parse_mode="HTML",
        reply_markup=keyboards.cancel_keyboard(),
    )


@router.message(NewGroupForm.name)
async def ng_name(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    await state.update_data(name=msg.text.strip())
    await msg.answer(
        "👥 <b>New Group</b> - Step 2/2\n\nSelect the <b>bridge mode</b>:\n\n"
        "• <b>Broadcast</b> - all agents see each other's output\n"
        "• <b>Supervisor</b> - one agent directs the others",
        parse_mode="HTML",
        reply_markup=keyboards.bridge_mode_keyboard(),
    )
    await state.set_state(NewGroupForm.bridge_mode)


@router.callback_query(F.data.startswith("bridge:"), NewGroupForm.bridge_mode)
async def ng_bridge_mode(cb: CallbackQuery, state: FSMContext) -> None:
    mode = cb.data.split(":", 1)[1]
    data = await state.get_data()
    gid = await bridge_mod.create_group(data["name"], mode)
    await state.clear()
    icon = "📡" if mode == "broadcast" else "👑"
    await cb.message.edit_text(
        f"✅ <b>Group created!</b>\n\n"
        f"{icon} <b>{data['name']}</b> [{mode}]\n"
        f"ID: #{gid}\n\n"
        f"Add agents with:\n<code>/add_to_group {gid} &lt;agent_id&gt;</code>",
        parse_mode="HTML",
        reply_markup=keyboards.group_detail_keyboard(gid),
    )
    await cb.answer()


@router.message(Command("add_to_group"))
async def cmd_add_to_group(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await msg.answer("Usage: /add_to_group <group_id> <agent_id>")
        return
    try:
        gid = int(parts[1])
    except ValueError:
        await msg.answer("Group ID must be a number.")
        return
    agents = await orchestrator.list_agents()
    match = next((a for a in agents if a["id"].startswith(parts[2].strip())), None)
    if not match:
        await msg.answer("Agent not found.")
        return
    group = await bridge_mod.get_group(gid)
    if not group:
        await msg.answer("Group not found.")
        return
    await bridge_mod.add_agent_to_group(gid, match["id"])
    b = await bridge_mod.get_or_create_bridge(gid)
    b.subscribe(match["id"])
    await msg.answer(
        f"✅ <b>{match['name']}</b> added to <b>{group['name']}</b>.",
        parse_mode="HTML",
        reply_markup=keyboards.group_detail_keyboard(gid),
    )


@router.message(Command("remove_from_group"))
async def cmd_remove_from_group(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await msg.answer("Usage: /remove_from_group <group_id> <agent_id>")
        return
    agents = await orchestrator.list_agents()
    match = next((a for a in agents if a["id"].startswith(parts[2].strip())), None)
    if not match:
        await msg.answer("Agent not found.")
        return
    await bridge_mod.remove_agent_from_group(match["id"])
    b = bridge_mod.get_bridge(int(parts[1]))
    if b:
        b.unsubscribe(match["id"])
    await msg.answer(f"<b>{match['name']}</b> removed from group.", parse_mode="HTML")


@router.message(Command("dissolve_group"))
async def cmd_dissolve_group(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Usage: /dissolve_group <id>")
        return
    try:
        gid = int(parts[1])
    except ValueError:
        await msg.answer("Group ID must be a number.")
        return
    group = await bridge_mod.get_group(gid)
    if not group:
        await msg.answer("Group not found.")
        return
    await bridge_mod.dissolve_group(gid)
    await msg.answer(f"💣 Group <b>{group['name']}</b> dissolved.", parse_mode="HTML",
                     reply_markup=keyboards.back_to_menu())
