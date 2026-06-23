import asyncio
import logging
from datetime import datetime
from storage import db

log = logging.getLogger(__name__)

_pending: dict[int, asyncio.Future] = {}


async def create_approval_request(agent_id: str, prompt: str) -> int:
    cur = await db.execute(
        "INSERT INTO approval_requests (agent_id, prompt, status) VALUES (?,?,'pending')",
        (agent_id, prompt),
    )
    request_id = cur.lastrowid
    loop = asyncio.get_running_loop()
    _pending[request_id] = loop.create_future()
    log.info("Approval request %d created for agent %s", request_id, agent_id)
    return request_id


async def wait_for_decision(request_id: int, timeout: float = 300.0) -> bool:
    fut = _pending.get(request_id)
    if fut is None:
        return False
    try:
        return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
    except asyncio.TimeoutError:
        await resolve_request(request_id, approved=False)
        return False


async def resolve_request(request_id: int, approved: bool) -> bool:
    fut = _pending.pop(request_id, None)
    status = "approved" if approved else "denied"
    await db.execute(
        "UPDATE approval_requests SET status=?, resolved_at=? WHERE id=? AND status='pending'",
        (status, datetime.utcnow().isoformat(), request_id),
    )
    if fut and not fut.done():
        fut.set_result(approved)
    log.info("Approval request %d resolved: %s", request_id, status)
    return True


async def get_pending_requests() -> list:
    return await db.fetchall(
        """SELECT ar.*, a.name as agent_name
           FROM approval_requests ar
           LEFT JOIN agents a ON ar.agent_id = a.id
           WHERE ar.status = 'pending'
           ORDER BY ar.requested_at ASC"""
    )


async def get_request(request_id: int) -> db.aiosqlite.Row | None:
    return await db.fetchone("SELECT * FROM approval_requests WHERE id = ?", (request_id,))
