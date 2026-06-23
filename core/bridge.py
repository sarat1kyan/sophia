import asyncio
import logging
from storage import db

log = logging.getLogger(__name__)


class Bridge:
    def __init__(self, group_id: int, bridge_mode: str = "broadcast"):
        self.group_id = group_id
        self.bridge_mode = bridge_mode
        self._queues: dict[str, asyncio.Queue] = {}

    def subscribe(self, agent_id: str) -> asyncio.Queue:
        if agent_id not in self._queues:
            self._queues[agent_id] = asyncio.Queue()
        return self._queues[agent_id]

    def unsubscribe(self, agent_id: str) -> None:
        self._queues.pop(agent_id, None)

    async def broadcast(self, sender_id: str, sender_name: str, content: str) -> None:
        await db.execute(
            "INSERT INTO messages (session_id, agent_id, role, content) VALUES (?,?,?,?)",
            (None, sender_id, "peer", f"[{sender_name}] {content}"),
        )
        for aid, q in self._queues.items():
            if aid != sender_id:
                await q.put({"sender_id": sender_id, "sender_name": sender_name, "content": content})

    async def receive(self, agent_id: str, timeout: float = 0.1) -> dict | None:
        q = self._queues.get(agent_id)
        if q is None:
            return None
        try:
            return await asyncio.wait_for(q.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None


_bridges: dict[int, Bridge] = {}


def get_bridge(group_id: int) -> Bridge | None:
    return _bridges.get(group_id)


async def get_or_create_bridge(group_id: int) -> Bridge:
    if group_id not in _bridges:
        row = await db.fetchone("SELECT bridge_mode FROM agent_groups WHERE id = ?", (group_id,))
        mode = row["bridge_mode"] if row else "broadcast"
        _bridges[group_id] = Bridge(group_id, mode)
    return _bridges[group_id]


def destroy_bridge(group_id: int) -> None:
    _bridges.pop(group_id, None)


async def create_group(name: str, bridge_mode: str = "broadcast") -> int:
    cur = await db.execute(
        "INSERT INTO agent_groups (name, bridge_mode) VALUES (?,?)",
        (name, bridge_mode),
    )
    return cur.lastrowid


async def list_groups() -> list:
    return await db.fetchall("SELECT * FROM agent_groups ORDER BY created_at DESC")


async def get_group(group_id: int) -> db.aiosqlite.Row | None:
    return await db.fetchone("SELECT * FROM agent_groups WHERE id = ?", (group_id,))


async def dissolve_group(group_id: int) -> None:
    await db.execute("UPDATE agents SET group_id = NULL WHERE group_id = ?", (group_id,))
    await db.execute("DELETE FROM agent_groups WHERE id = ?", (group_id,))
    destroy_bridge(group_id)


async def add_agent_to_group(group_id: int, agent_id: str) -> None:
    await db.execute("UPDATE agents SET group_id = ? WHERE id = ?", (group_id, agent_id))


async def remove_agent_from_group(agent_id: str) -> None:
    await db.execute("UPDATE agents SET group_id = NULL WHERE id = ?", (agent_id,))
