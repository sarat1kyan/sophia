import logging
from storage import db

log = logging.getLogger(__name__)


async def create_workspace(name: str, path: str, runner_type: str = "local", ssh_host_id: int | None = None) -> int:
    cur = await db.execute(
        "INSERT INTO workspaces (name, path, runner_type, ssh_host_id) VALUES (?,?,?,?)",
        (name, path, runner_type, ssh_host_id),
    )
    log.info("Workspace created: %s (%s)", name, path)
    return cur.lastrowid


async def get_workspace(workspace_id: int) -> db.aiosqlite.Row | None:
    return await db.fetchone("SELECT * FROM workspaces WHERE id = ?", (workspace_id,))


async def list_workspaces() -> list:
    return await db.fetchall(
        """SELECT w.*, s.alias as ssh_alias
           FROM workspaces w
           LEFT JOIN ssh_hosts s ON w.ssh_host_id = s.id
           ORDER BY w.created_at DESC"""
    )


async def update_workspace_path(workspace_id: int, path: str) -> None:
    await db.execute("UPDATE workspaces SET path=? WHERE id=?", (path, workspace_id))
    log.info("Workspace #%d path updated to %s", workspace_id, path)


async def delete_workspace(workspace_id: int) -> bool:
    cur = await db.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
    return cur.rowcount > 0


async def create_ssh_host(alias: str, host: str, port: int, username: str, key_path: str | None, password: str | None) -> int:
    cur = await db.execute(
        "INSERT INTO ssh_hosts (alias, host, port, username, key_path, password) VALUES (?,?,?,?,?,?)",
        (alias, host, port, username, key_path, password),
    )
    log.info("SSH host created: %s (%s@%s:%d)", alias, username, host, port)
    return cur.lastrowid


async def get_ssh_host(host_id: int) -> db.aiosqlite.Row | None:
    return await db.fetchone("SELECT * FROM ssh_hosts WHERE id = ?", (host_id,))


async def list_ssh_hosts() -> list:
    return await db.fetchall("SELECT * FROM ssh_hosts ORDER BY created_at DESC")


async def delete_ssh_host(host_id: int) -> bool:
    cur = await db.execute("DELETE FROM ssh_hosts WHERE id = ?", (host_id,))
    return cur.rowcount > 0
