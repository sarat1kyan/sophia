#!/usr/bin/env python3
import argparse
import asyncio
import logging
import logging.handlers
import os
import signal
import sys
from pathlib import Path

import yaml
from rich.console import Console
from rich.logging import RichHandler

console = Console()


def load_config(path: str = "config/config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def setup_logging(cfg: dict) -> None:
    level_name = cfg.get("sophia", {}).get("log_level", "INFO")
    log_file = cfg.get("sophia", {}).get("log_file", "logs/SOPHIA.log")
    level = getattr(logging, level_name.upper(), logging.INFO)

    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    handlers: list[logging.Handler] = [
        RichHandler(console=console, show_time=True, show_path=False, markup=True),
    ]

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    handlers.append(file_handler)

    logging.basicConfig(level=level, handlers=handlers)


def run_setup() -> None:
    import requests

    console.print("\n[bold cyan]SOPHIA Setup Wizard[/bold cyan]\n")

    token = console.input("[bold]Telegram Bot Token:[/bold] ").strip()
    console.print("Validating token...")
    try:
        resp = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        data = resp.json()
        if not data.get("ok"):
            console.print(f"[red]Invalid token: {data.get('description')}[/red]")
            sys.exit(1)
        bot_info = data["result"]
        console.print(f"[green]Token valid! Bot: @{bot_info['username']}[/green]")
    except Exception as e:
        console.print(f"[red]Could not validate token: {e}[/red]")
        sys.exit(1)

    admin_id_raw = console.input("[bold]Your Telegram user ID (admin):[/bold] ").strip()
    try:
        admin_id = int(admin_id_raw)
    except ValueError:
        console.print("[red]Invalid user ID[/red]")
        sys.exit(1)

    users_raw = console.input(
        "[bold]Approved user IDs (comma-separated, include your own):[/bold] "
    ).strip()
    approved = []
    for uid in users_raw.split(","):
        uid = uid.strip()
        if uid:
            try:
                approved.append(int(uid))
            except ValueError:
                pass
    if admin_id not in approved:
        approved.append(admin_id)

    Path("config").mkdir(exist_ok=True)
    Path("logs").mkdir(exist_ok=True)
    Path("storage").mkdir(exist_ok=True)

    config = {
        "telegram": {
            "bot_token": token,
            "admin_id": admin_id,
            "approved_users": approved,
        },
        "sophia": {
            "log_level": "INFO",
            "log_file": "logs/SOPHIA.log",
            "db_path": "storage/SOPHIA.db",
            "stream_chunk_lines": 1,
            "approval_timeout_seconds": 300,
        },
        "claude": {
            "cli_path": "claude",
            "default_flags": ["--permission-mode", "acceptEdits"],
        },
    }

    with open("config/config.yaml", "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    console.print("[green]config/config.yaml written.[/green]")

    asyncio.run(_init_db(config))
    console.print("[green]Database initialised.[/green]")

    console.print(
        "\n[bold green]Setup complete![/bold green]\n"
        "Start SOPHIA with:\n"
        "  [cyan]systemctl start SOPHIA[/cyan]  (Linux)\n"
        "  [cyan]python3 SOPHIA.py[/cyan]        (manual)\n"
    )


async def _init_db(cfg: dict) -> None:
    from storage.db import init_db
    await init_db(cfg["sophia"]["db_path"])
    await _seed_templates()


async def _seed_templates() -> None:
    import glob
    from storage import db

    for yaml_path in glob.glob("templates/*.yaml"):
        with open(yaml_path) as f:
            tpl = yaml.safe_load(f)
        if not tpl or "name" not in tpl:
            continue
        existing = await db.fetchone("SELECT id FROM templates WHERE name = ?", (tpl["name"],))
        if not existing:
            await db.execute(
                "INSERT INTO templates (name, description, system_prompt, is_builtin) VALUES (?,?,?,1)",
                (tpl["name"], tpl.get("description", ""), tpl.get("system_prompt", "")),
            )


async def main_async(cfg: dict) -> None:
    setup_logging(cfg)
    log = logging.getLogger("SOPHIA")
    log.info("Starting SOPHIA")

    from storage.db import init_db, close_db
    from core import orchestrator
    from bot.bot import create_bot, create_dispatcher, setup_commands
    from bot.auth import init as auth_init

    db_path = cfg["sophia"]["db_path"]
    await init_db(db_path)
    await _seed_templates()

    approved = cfg["telegram"].get("approved_users", [])
    admin_id = cfg["telegram"].get("admin_id", 0)
    auth_init(approved, admin_id)

    bot = create_bot(cfg["telegram"]["bot_token"])
    dp = create_dispatcher()
    orchestrator.init(bot, cfg)
    await orchestrator.load_agents_from_db()

    await setup_commands(bot)

    loop = asyncio.get_event_loop()

    def _shutdown(sig, frame):
        log.info("Received signal %s, shutting down...", sig)
        loop.create_task(_graceful_shutdown(dp, bot, close_db, orchestrator))

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    log.info("Bot polling started")
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        await orchestrator.shutdown_all()
        await close_db()
        log.info("SOPHIA stopped")


async def _graceful_shutdown(dp, bot, close_db_fn, orchestrator_mod):
    await orchestrator_mod.shutdown_all()
    await dp.stop_polling()
    await close_db_fn()


def main() -> None:
    parser = argparse.ArgumentParser(description="SOPHIA - Claude Code Agent Orchestrator")
    parser.add_argument("--setup", action="store_true", help="Run first-time setup wizard")
    parser.add_argument("--config", default="config/config.yaml", help="Config file path")
    args = parser.parse_args()

    if args.setup:
        run_setup()
        return

    if not Path(args.config).exists():
        console.print(
            f"[red]Config not found: {args.config}[/red]\n"
            "Run [cyan]python3 SOPHIA.py --setup[/cyan] first."
        )
        sys.exit(1)

    cfg = load_config(args.config)
    asyncio.run(main_async(cfg))


if __name__ == "__main__":
    main()
