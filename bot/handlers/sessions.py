import logging
import tempfile
import os
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import Command

from core import session as session_mod
from bot import keyboards

log = logging.getLogger(__name__)
router = Router()


@router.message(Command("sessions"))
async def cmd_sessions(msg: Message) -> None:
    sessions = await session_mod.list_sessions()
    if not sessions:
        await msg.answer("<b>💬 Sessions</b>\n\nNo sessions yet.",
                         parse_mode="HTML", reply_markup=keyboards.back_to_menu())
        return
    lines = ["<b>💬 Sessions</b>\n"]
    for s in sessions:
        lines.append(f"• #{s['id']} <b>{s['agent_name'] or 'unknown'}</b> - {str(s['updated_at'])[:16]}")
    lines.append("\n<i>Tap a session to view or export it.</i>")
    await msg.answer("\n".join(lines), parse_mode="HTML",
                     reply_markup=keyboards.sessions_list_keyboard(sessions))


@router.message(Command("session"))
async def cmd_session(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Usage: /session <id>")
        return
    try:
        sid = int(parts[1])
    except ValueError:
        await msg.answer("Session ID must be a number.")
        return
    await _show_session(msg, sid)


async def _show_session(target, sid: int) -> None:
    messages = await session_mod.get_session_messages(sid)
    if not messages:
        text = f"Session #{sid} not found or empty."
        if isinstance(target, Message):
            await target.answer(text)
        else:
            await target.message.edit_text(text, reply_markup=keyboards.back_to_menu())
        return
    lines = [f"<b>💬 Session #{sid}</b>"]
    if len(messages) > 20:
        lines.append(f"<i>(showing last 20 of {len(messages)} messages)</i>")
    lines.append("")
    for m in messages[-20:]:
        role = m["role"].upper()
        content = (m["content"] or "")[:300].replace("<", "&lt;").replace(">", "&gt;")
        lines.append(f"<b>[{role}]</b> <i>{str(m['timestamp'])[:16]}</i>\n{content}")
        lines.append("")
    text = "\n".join(lines)
    if isinstance(target, Message):
        await target.answer(text, parse_mode="HTML",
                            reply_markup=keyboards.session_detail_keyboard(sid))
    else:
        await target.message.edit_text(text, parse_mode="HTML",
                                       reply_markup=keyboards.session_detail_keyboard(sid))


@router.callback_query(F.data.startswith("session_detail:"))
async def cb_session_detail(cb: CallbackQuery) -> None:
    sid = int(cb.data.split(":", 1)[1])
    await _show_session(cb, sid)
    await cb.answer()


@router.callback_query(F.data.startswith("session_export:"))
async def cb_session_export(cb: CallbackQuery) -> None:
    sid = int(cb.data.split(":", 1)[1])
    await _do_export(cb.message, sid)
    await cb.answer()


@router.callback_query(F.data.startswith("session_clear_confirm:"))
async def cb_session_clear_confirm(cb: CallbackQuery) -> None:
    sid = int(cb.data.split(":", 1)[1])
    await cb.message.edit_text(
        f"⚠️ Clear all messages in session #{sid}?",
        reply_markup=keyboards.session_clear_confirm_keyboard(sid),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("session_clear:"))
async def cb_session_clear(cb: CallbackQuery) -> None:
    sid = int(cb.data.split(":", 1)[1])
    await session_mod.clear_session(sid)
    await cb.message.edit_text(f"🗑 Session #{sid} cleared.",
                               reply_markup=keyboards.back_to_menu())
    await cb.answer("Cleared.")


@router.message(Command("clear_session"))
async def cmd_clear_session(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Usage: /clear_session <id>")
        return
    try:
        sid = int(parts[1])
    except ValueError:
        await msg.answer("ID must be a number.")
        return
    await session_mod.clear_session(sid)
    await msg.answer(f"🗑 Session #{sid} cleared.")


@router.message(Command("export_session"))
async def cmd_export_session(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Usage: /export_session <id>")
        return
    try:
        sid = int(parts[1])
    except ValueError:
        await msg.answer("ID must be a number.")
        return
    await _do_export(msg, sid)


async def _do_export(target, sid: int) -> None:
    text = await session_mod.export_session_text(sid)
    if not text.strip():
        if isinstance(target, Message):
            await target.answer("Session not found or empty.")
        else:
            await target.answer("Session not found or empty.")
        return
    with tempfile.NamedTemporaryFile(mode="w", suffix=f"_session_{sid}.txt",
                                     delete=False, encoding="utf-8") as f:
        f.write(text)
        tmp = f.name
    try:
        doc = FSInputFile(tmp, filename=f"session_{sid}.txt")
        if isinstance(target, Message):
            await target.answer_document(doc, caption=f"📤 Session #{sid} export")
        else:
            await target.answer_document(doc, caption=f"📤 Session #{sid} export")
    finally:
        os.unlink(tmp)
