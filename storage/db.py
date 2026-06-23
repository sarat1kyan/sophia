import aiosqlite
import logging
from pathlib import Path
from storage.models import SCHEMA

log = logging.getLogger(__name__)

_db: aiosqlite.Connection | None = None


_MIGRATIONS = [
    "ALTER TABLE agents ADD COLUMN run_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE agents ADD COLUMN last_run_at DATETIME",
    "ALTER TABLE agents ADD COLUMN settings TEXT",
    "ALTER TABLE sessions ADD COLUMN claude_session_id TEXT",
]


async def _run_migrations(conn: aiosqlite.Connection) -> None:
    for sql in _MIGRATIONS:
        try:
            await conn.execute(sql)
        except Exception:
            pass  # column already exists
    await conn.commit()


async def init_db(path: str) -> None:
    global _db
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _db = await aiosqlite.connect(path)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA foreign_keys = ON")
    await _db.executescript(SCHEMA)
    await _run_migrations(_db)
    await _db.commit()
    log.info("Database initialised at %s", path)


async def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("Database not initialised - call init_db() first")
    return _db


async def close_db() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None


async def execute(sql: str, params: tuple = ()) -> aiosqlite.Cursor:
    db = await get_db()
    cur = await db.execute(sql, params)
    await db.commit()
    return cur


async def fetchone(sql: str, params: tuple = ()) -> aiosqlite.Row | None:
    db = await get_db()
    async with db.execute(sql, params) as cur:
        return await cur.fetchone()


async def fetchall(sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
    db = await get_db()
    async with db.execute(sql, params) as cur:
        return await cur.fetchall()
