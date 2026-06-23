import logging
from storage import db

log = logging.getLogger(__name__)


async def create_session(agent_id: str) -> int:
    cur = await db.execute(
        "INSERT INTO sessions (agent_id) VALUES (?)", (agent_id,)
    )
    return cur.lastrowid


async def get_or_create_session(agent_id: str) -> int:
    row = await db.fetchone(
        "SELECT id FROM sessions WHERE agent_id = ? ORDER BY created_at DESC LIMIT 1",
        (agent_id,),
    )
    if row:
        return row["id"]
    return await create_session(agent_id)


async def store_claude_session_id(session_id: int, claude_session_id: str) -> None:
    await db.execute(
        "UPDATE sessions SET claude_session_id=? WHERE id=?",
        (claude_session_id, session_id),
    )


async def get_last_claude_session_id(agent_id: str) -> str | None:
    row = await db.fetchone(
        """SELECT claude_session_id FROM sessions
           WHERE agent_id=? AND claude_session_id IS NOT NULL
           ORDER BY created_at DESC LIMIT 1""",
        (agent_id,),
    )
    return row["claude_session_id"] if row else None


async def save_message(session_id: int, agent_id: str, role: str, content: str) -> None:
    await db.execute(
        "INSERT INTO messages (session_id, agent_id, role, content) VALUES (?,?,?,?)",
        (session_id, agent_id, role, content),
    )
    await db.execute(
        "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (session_id,),
    )


async def get_session_messages(session_id: int) -> list:
    return await db.fetchall(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY timestamp ASC",
        (session_id,),
    )


async def list_sessions() -> list:
    return await db.fetchall(
        """SELECT s.*, a.name as agent_name
           FROM sessions s
           LEFT JOIN agents a ON s.agent_id = a.id
           ORDER BY s.updated_at DESC""",
    )


async def clear_session(session_id: int) -> None:
    await db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    await db.execute(
        "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (session_id,),
    )


async def export_session_text(session_id: int) -> str:
    messages = await get_session_messages(session_id)
    lines = []
    for m in messages:
        lines.append(f"[{m['timestamp']}] [{m['role'].upper()}] {m['content']}")
        lines.append("")
    return "\n".join(lines)
