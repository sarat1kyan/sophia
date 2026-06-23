import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from core import approval as approval_mod
from bot import keyboards

log = logging.getLogger(__name__)
router = Router()


@router.message(Command("pending"))
async def cmd_pending(msg: Message) -> None:
    requests = await approval_mod.get_pending_requests()
    if not requests:
        await msg.answer("No pending approval requests.")
        return
    lines = ["<b>Pending Approvals</b>\n"]
    for r in requests:
        lines.append(
            f"• #{r['id']} <b>{r['agent_name'] or r['agent_id']}</b>\n"
            f"  <code>{r['prompt'][:200]}</code>\n"
            f"  Requested: {r['requested_at']}"
        )
    await msg.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("approve"))
async def cmd_approve(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Usage: /approve <request_id>")
        return
    try:
        rid = int(parts[1])
    except ValueError:
        await msg.answer("Request ID must be a number.")
        return
    req = await approval_mod.get_request(rid)
    if not req:
        await msg.answer("Request not found.")
        return
    if req["status"] != "pending":
        await msg.answer(f"Request already {req['status']}.")
        return
    await approval_mod.resolve_request(rid, approved=True)
    await msg.answer(f"✅ Request #{rid} approved.")


@router.message(Command("deny"))
async def cmd_deny(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Usage: /deny <request_id>")
        return
    try:
        rid = int(parts[1])
    except ValueError:
        await msg.answer("Request ID must be a number.")
        return
    req = await approval_mod.get_request(rid)
    if not req:
        await msg.answer("Request not found.")
        return
    if req["status"] != "pending":
        await msg.answer(f"Request already {req['status']}.")
        return
    await approval_mod.resolve_request(rid, approved=False)
    await msg.answer(f"❌ Request #{rid} denied.")


@router.callback_query(F.data.startswith("approve:"))
async def cb_approve(cb: CallbackQuery) -> None:
    try:
        rid = int(cb.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await cb.answer("Invalid request ID", show_alert=True)
        return
    req = await approval_mod.get_request(rid)
    if not req or req["status"] != "pending":
        await cb.answer("Request no longer pending.", show_alert=True)
        return
    await approval_mod.resolve_request(rid, approved=True)
    await cb.message.edit_text(
        cb.message.text + "\n\n✅ <b>Approved</b>",
        parse_mode="HTML",
    )
    await cb.answer("Approved!")


@router.callback_query(F.data.startswith("deny:"))
async def cb_deny(cb: CallbackQuery) -> None:
    try:
        rid = int(cb.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await cb.answer("Invalid request ID", show_alert=True)
        return
    req = await approval_mod.get_request(rid)
    if not req or req["status"] != "pending":
        await cb.answer("Request no longer pending.", show_alert=True)
        return
    await approval_mod.resolve_request(rid, approved=False)
    await cb.message.edit_text(
        cb.message.text + "\n\n❌ <b>Denied</b>",
        parse_mode="HTML",
    )
    await cb.answer("Denied!")
