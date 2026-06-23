import asyncio
import logging
import subprocess
import time
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

from bot.auth import is_admin, add_user, remove_user, list_users
from storage import db

log = logging.getLogger(__name__)
router = Router()
_start_time = time.time()


def _admin_only(handler):
    async def wrapper(msg: Message, *args, **kwargs):
        if not msg.from_user or not is_admin(msg.from_user.id):
            await msg.answer("⛔ Admin only.")
            return
        return await handler(msg, *args, **kwargs)
    wrapper.__name__ = handler.__name__
    return wrapper


@router.message(Command("add_user"))
@_admin_only
async def cmd_add_user(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Usage: /add_user <telegram_id>")
        return
    try:
        uid = int(parts[1].strip())
    except ValueError:
        await msg.answer("User ID must be a number.")
        return
    add_user(uid)
    await db.execute(
        "INSERT OR IGNORE INTO users (telegram_id, role) VALUES (?, 'user')", (uid,)
    )
    await msg.answer(f"✅ User {uid} added.")


@router.message(Command("remove_user"))
@_admin_only
async def cmd_remove_user(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Usage: /remove_user <telegram_id>")
        return
    try:
        uid = int(parts[1].strip())
    except ValueError:
        await msg.answer("User ID must be a number.")
        return
    remove_user(uid)
    await db.execute("DELETE FROM users WHERE telegram_id = ?", (uid,))
    await msg.answer(f"User {uid} removed.")


@router.message(Command("users"))
@_admin_only
async def cmd_users(msg: Message) -> None:
    users = list_users()
    rows = await db.fetchall("SELECT * FROM users ORDER BY added_at DESC")
    lines = ["<b>Approved Users</b>\n"]
    for r in rows:
        lines.append(f"• {r['telegram_id']} ({r['username'] or 'unknown'}) [{r['role']}]")
    if not rows:
        lines.append("No users in DB (in-memory: " + str(users) + ")")
    await msg.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("logs"))
@_admin_only
async def cmd_logs(msg: Message) -> None:
    try:
        import yaml
        with open("config/config.yaml") as f:
            cfg = yaml.safe_load(f)
        log_file = cfg.get("sophia", {}).get("log_file", "logs/SOPHIA.log")
    except Exception:
        log_file = "logs/SOPHIA.log"

    try:
        result = subprocess.run(
            ["tail", "-n", "50", log_file],
            capture_output=True, text=True, timeout=5,
        )
        content = result.stdout or "(empty)"
    except Exception as e:
        content = f"Could not read log: {e}"

    if len(content) > 4000:
        content = "..." + content[-4000:]
    await msg.answer(f"<pre>{content}</pre>", parse_mode="HTML")


@router.message(Command("restart"))
@_admin_only
async def cmd_restart(msg: Message) -> None:
    await msg.answer("Restarting SOPHIA...")
    try:
        subprocess.Popen(["systemctl", "restart", "SOPHIA"])
    except Exception as e:
        await msg.answer(f"Could not restart: {e}")


@router.message(Command("config"))
@_admin_only
async def cmd_config(msg: Message) -> None:
    try:
        import yaml
        with open("config/config.yaml") as f:
            cfg = yaml.safe_load(f) or {}
        if "telegram" in cfg and "bot_token" in cfg["telegram"]:
            token = cfg["telegram"]["bot_token"]
            cfg["telegram"]["bot_token"] = token[:8] + "..." + token[-4:]
        text = yaml.dump(cfg, default_flow_style=False, allow_unicode=True)
    except Exception as e:
        text = f"Could not read config: {e}"
    await msg.answer(f"<pre>{text}</pre>", parse_mode="HTML")


@router.message(Command("ping"))
async def cmd_ping(msg: Message) -> None:
    uptime = int(time.time() - _start_time)
    h, r = divmod(uptime, 3600)
    m, s = divmod(r, 60)
    from core import orchestrator
    stats = await orchestrator.agent_stats()
    running = stats.get("actually_running", 0)
    total   = sum(v for k, v in stats.items() if k not in ("in_memory", "actually_running"))
    await msg.answer(
        f"🏓 <b>Pong!</b>\n\n"
        f"Uptime: <code>{h}h {m}m {s}s</code>\n"
        f"Agents: {total} total, {running} running\n"
        f"In-memory: {stats.get('in_memory', 0)}",
        parse_mode="HTML",
    )


@router.message(Command("stop_all"))
@_admin_only
async def cmd_stop_all(msg: Message) -> None:
    from core import orchestrator
    count = await orchestrator.stop_all_agents()
    await msg.answer(f"⏹ Stopped <b>{count}</b> running agent(s).", parse_mode="HTML")


@router.message(Command("kill_all"))
@_admin_only
async def cmd_kill_all(msg: Message) -> None:
    from core import orchestrator
    count = await orchestrator.kill_all_agents()
    await msg.answer(f"💀 Killed <b>{count}</b> running agent(s).", parse_mode="HTML")
