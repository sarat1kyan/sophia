import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from core import workspace as ws_mod
from bot import keyboards
from transport.ssh_runner import SSHRunner

log = logging.getLogger(__name__)
router = Router()


class NewSSHHostForm(StatesGroup):
    alias          = State()
    host           = State()
    port           = State()
    username       = State()
    auth_type      = State()
    key_or_password = State()


@router.message(Command("ssh_hosts"))
async def cmd_ssh_hosts(msg: Message) -> None:
    hosts = await ws_mod.list_ssh_hosts()
    if not hosts:
        await msg.answer(
            "<b>🌐 SSH Hosts</b>\n\nNo SSH hosts configured yet.",
            parse_mode="HTML",
            reply_markup=keyboards.ssh_list_keyboard([]),
        )
        return
    lines = ["<b>🌐 SSH Hosts</b>\n"]
    for h in hosts:
        auth = "🔑 key" if h["key_path"] else "🔐 password"
        lines.append(f"🖧 <b>{h['alias']}</b> - {h['username']}@{h['host']}:{h['port']} [{auth}]")
    lines.append("\n<i>Tap a host to test or delete it.</i>")
    await msg.answer("\n".join(lines), parse_mode="HTML",
                     reply_markup=keyboards.ssh_list_keyboard(hosts))


@router.callback_query(F.data.startswith("ssh_detail:"))
async def cb_ssh_detail(cb: CallbackQuery) -> None:
    hid = int(cb.data.split(":", 1)[1])
    h = await ws_mod.get_ssh_host(hid)
    if not h:
        await cb.answer("SSH host not found.", show_alert=True)
        return
    auth = "🔑 " + h["key_path"] if h["key_path"] else "🔐 password"
    text = (
        f"<b>🖧 {h['alias']}</b>\n\n"
        f"Host:     <code>{h['host']}:{h['port']}</code>\n"
        f"User:     <code>{h['username']}</code>\n"
        f"Auth:     {auth}\n"
        f"Added:    {str(h['created_at'])[:16]}"
    )
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=keyboards.ssh_detail_keyboard(hid))
    await cb.answer()


@router.callback_query(F.data.startswith("ssh_test:"))
async def cb_ssh_test(cb: CallbackQuery) -> None:
    hid = int(cb.data.split(":", 1)[1])
    h = await ws_mod.get_ssh_host(hid)
    if not h:
        await cb.answer("SSH host not found.", show_alert=True)
        return
    await cb.answer("Testing…")
    await cb.message.answer(f"🔌 Testing connection to <b>{h['alias']}</b>…", parse_mode="HTML")
    runner = SSHRunner(host=h["host"], port=h["port"], username=h["username"],
                       key_path=h["key_path"], password=h["password"])
    ok, detail = await runner.test_connection()
    if ok:
        await cb.message.answer(f"✅ <b>{h['alias']}</b> - connection successful!", parse_mode="HTML")
    else:
        await cb.message.answer(f"❌ <b>{h['alias']}</b> - failed:\n<code>{detail}</code>", parse_mode="HTML")


@router.callback_query(F.data.startswith("ssh_delete_confirm:"))
async def cb_ssh_delete_confirm(cb: CallbackQuery) -> None:
    hid = int(cb.data.split(":", 1)[1])
    h = await ws_mod.get_ssh_host(hid)
    name = h["alias"] if h else f"#{hid}"
    await cb.message.edit_text(
        f"⚠️ Delete SSH host <b>{name}</b>?",
        parse_mode="HTML",
        reply_markup=keyboards.ssh_delete_confirm_keyboard(hid),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("ssh_delete:"))
async def cb_ssh_delete(cb: CallbackQuery) -> None:
    hid = int(cb.data.split(":", 1)[1])
    await ws_mod.delete_ssh_host(hid)
    await cb.message.edit_text("🗑 SSH host deleted.", reply_markup=keyboards.back_to_menu())
    await cb.answer("Deleted.")


@router.message(Command("new_ssh_host"))
async def cmd_new_ssh_host(msg: Message, state: FSMContext) -> None:
    await state.set_state(NewSSHHostForm.alias)
    await msg.answer(
        "🌐 <b>New SSH Host</b> - Step 1/5\n\nEnter an <b>alias</b> for this host:",
        parse_mode="HTML",
        reply_markup=keyboards.cancel_keyboard(),
    )


@router.message(NewSSHHostForm.alias)
async def ssh_alias(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    await state.update_data(alias=msg.text.strip())
    await msg.answer("🌐 <b>New SSH Host</b> - Step 2/5\n\nEnter the <b>hostname or IP</b>:", parse_mode="HTML")
    await state.set_state(NewSSHHostForm.host)


@router.message(NewSSHHostForm.host)
async def ssh_host(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    await state.update_data(host=msg.text.strip())
    await msg.answer("🌐 <b>New SSH Host</b> - Step 3/5\n\nEnter the <b>port</b> (default: 22):", parse_mode="HTML")
    await state.set_state(NewSSHHostForm.port)


@router.message(NewSSHHostForm.port)
async def ssh_port(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    text = msg.text.strip()
    try:
        port = int(text)
    except ValueError:
        await msg.answer("Port must be a number.")
        return
    await state.update_data(port=port)
    await msg.answer("🌐 <b>New SSH Host</b> - Step 4/5\n\nEnter the <b>SSH username</b>:", parse_mode="HTML")
    await state.set_state(NewSSHHostForm.username)


@router.message(NewSSHHostForm.username)
async def ssh_username(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    await state.update_data(username=msg.text.strip())
    await msg.answer(
        "🌐 <b>New SSH Host</b> - Step 5/5\n\nSelect authentication method:",
        parse_mode="HTML",
        reply_markup=keyboards.auth_type_keyboard(),
    )
    await state.set_state(NewSSHHostForm.auth_type)


@router.callback_query(F.data.startswith("ssh_auth:"), NewSSHHostForm.auth_type)
async def ssh_auth_type(cb: CallbackQuery, state: FSMContext) -> None:
    auth = cb.data.split(":", 1)[1]
    await state.update_data(auth_type=auth)
    if auth == "key":
        await cb.message.edit_text("Enter the full <b>path to your private key</b>:\n\nExample: <code>/root/.ssh/id_rsa</code>",
                                   parse_mode="HTML")
    else:
        await cb.message.edit_text("Enter the <b>SSH password</b>:", parse_mode="HTML")
    await state.set_state(NewSSHHostForm.key_or_password)
    await cb.answer()


@router.message(NewSSHHostForm.key_or_password)
async def ssh_key_or_password(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    data = await state.get_data()
    auth_type = data.get("auth_type", "password")
    key_path  = msg.text.strip() if auth_type == "key"      else None
    password  = msg.text.strip() if auth_type == "password" else None
    hid = await ws_mod.create_ssh_host(
        alias=data["alias"], host=data["host"], port=data.get("port", 22),
        username=data["username"], key_path=key_path, password=password,
    )
    await state.clear()
    await msg.answer(
        f"✅ <b>SSH host added!</b>\n\n"
        f"🖧 <b>{data['alias']}</b> - {data['username']}@{data['host']}:{data.get('port',22)}\n"
        f"ID: #{hid}\n\n"
        f"Tap the button below to test the connection.",
        parse_mode="HTML",
        reply_markup=keyboards.ssh_detail_keyboard(hid),
    )


@router.message(Command("test_ssh"))
async def cmd_test_ssh(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Usage: /test_ssh <id>")
        return
    try:
        hid = int(parts[1])
    except ValueError:
        await msg.answer("ID must be a number.")
        return
    h = await ws_mod.get_ssh_host(hid)
    if not h:
        await msg.answer("SSH host not found.")
        return
    await msg.answer(f"🔌 Testing <b>{h['alias']}</b>…", parse_mode="HTML")
    runner = SSHRunner(host=h["host"], port=h["port"], username=h["username"],
                       key_path=h["key_path"], password=h["password"])
    ok, detail = await runner.test_connection()
    if ok:
        await msg.answer(f"✅ <b>{h['alias']}</b> - connection successful!\n<code>{detail}</code>",
                         parse_mode="HTML")
    else:
        await msg.answer(f"❌ <b>{h['alias']}</b> - failed:\n<code>{detail}</code>",
                         parse_mode="HTML")


@router.message(Command("delete_ssh_host"))
async def cmd_delete_ssh_host(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Usage: /delete_ssh_host <id>")
        return
    try:
        hid = int(parts[1])
    except ValueError:
        await msg.answer("ID must be a number.")
        return
    ok = await ws_mod.delete_ssh_host(hid)
    await msg.answer(f"🗑 SSH host #{hid} deleted." if ok else "SSH host not found.")
