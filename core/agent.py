import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Callable, Awaitable

from storage import db
from core import approval as approval_mod
from core import bridge as bridge_mod
from core.session import create_session, save_message, store_claude_session_id
from streaming.streamer import AgentStreamer
from transport.local_runner import LocalRunner
from transport.ssh_runner import SSHRunner

log = logging.getLogger(__name__)

Runner = LocalRunner | SSHRunner

_config_cache: dict = {}


def _load_config() -> dict:
    global _config_cache
    if _config_cache:
        return _config_cache
    try:
        import yaml
        with open("config/config.yaml") as f:
            _config_cache = yaml.safe_load(f) or {}
    except Exception:
        _config_cache = {}
    return _config_cache


def _build_extra_flags(settings: dict, resume_id: str | None = None) -> list[str]:
    flags: list[str] = []
    if settings.get("skip_permissions"):
        flags += ["--permission-mode", "acceptEdits"]
    effort = settings.get("effort")
    if effort:
        flags += ["--effort", effort]
    model = settings.get("model")
    if model:
        flags += ["--model", model]
    budget = settings.get("max_budget_usd")
    if budget is not None:
        flags += ["--max-budget-usd", str(budget)]
    allowed_tools = settings.get("allowed_tools")
    if allowed_tools:
        flags += ["--allowedTools", allowed_tools]
    for d in settings.get("add_dirs") or []:
        flags += ["--add-dir", d]
    if resume_id:
        flags += ["--resume", resume_id]
    return flags


@dataclass
class Agent:
    agent_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    role: str = ""
    system_prompt: str = ""
    workspace_path: str = "/tmp"
    runner: Runner | None = None
    status: str = "idle"
    group_id: int | None = None
    settings: dict = field(default_factory=dict)
    _task: asyncio.Task | None = field(default=None, repr=False)
    _streamer: AgentStreamer | None = field(default=None, repr=False)
    _notify_cb: Callable[[str, str], Awaitable[None]] | None = field(default=None, repr=False)

    def set_notify(self, cb: Callable[[str, str], Awaitable[None]]) -> None:
        self._notify_cb = cb

    async def _approval_gate(self, prompt_text: str) -> bool:
        request_id = await approval_mod.create_approval_request(self.agent_id, prompt_text)
        if self._notify_cb:
            await self._notify_cb("approval", f"{request_id}:{prompt_text}")
        cfg = _load_config()
        timeout = cfg.get("sophia", {}).get("approval_timeout_seconds", 300)
        return await approval_mod.wait_for_decision(request_id, timeout=float(timeout))

    async def _send_error(self, streamer: AgentStreamer, msg: str) -> None:
        from html import escape
        log.error("Agent %s (%s): %s", self.agent_id[:8], self.name, msg)
        self.status = "error"
        await _update_status(self.agent_id, "error")
        try:
            await streamer.bot.send_message(
                streamer.chat_id,
                f"❌ <b>[{escape(self.name)}]</b> {msg}",
                parse_mode="HTML",
            )
        except Exception:
            pass

    async def start(self, prompt: str, streamer: AgentStreamer, resume: bool = False) -> None:
        self._streamer = streamer

        if self.runner is None:
            await self._send_error(streamer, "No runner attached. Delete and recreate this agent.")
            return

        if isinstance(self.runner, LocalRunner):
            if not os.path.isdir(self.workspace_path):
                await self._send_error(
                    streamer,
                    f"Workspace path does not exist: <code>{self.workspace_path}</code>\n\n"
                    f"Fix it with /workspaces → edit path, or create the directory first.",
                )
                return

        self.status = "running"
        await _update_status(self.agent_id, "running")
        await db.execute(
            "UPDATE agents SET last_run_at=CURRENT_TIMESTAMP, run_count=run_count+1 WHERE id=?",
            (self.agent_id,),
        )
        self.runner.set_approval_callback(self._approval_gate)

        # Create a fresh session for each run
        session_id = await create_session(self.agent_id)
        await save_message(session_id, self.agent_id, "user", prompt)

        # Wire up session_id capture from stream
        async def _on_session_id(sid: str) -> None:
            await store_claude_session_id(session_id, sid)

        if hasattr(self.runner, "set_session_id_callback"):
            self.runner.set_session_id_callback(_on_session_id)

        # Resolve resume flag
        resume_id: str | None = None
        if resume and hasattr(self.runner, "claude_session_id"):
            from core.session import get_last_claude_session_id
            resume_id = await get_last_claude_session_id(self.agent_id)

        extra_flags = _build_extra_flags(self.settings, resume_id=resume_id)

        bridge: bridge_mod.Bridge | None = None
        if self.group_id:
            bridge = await bridge_mod.get_or_create_bridge(self.group_id)
            bridge.subscribe(self.agent_id)

        full_prompt = f"{self.system_prompt}\n\nTask:\n{prompt}" if self.system_prompt else prompt

        cfg = _load_config()
        timeout_secs = self.settings.get("timeout_seconds") or cfg.get("sophia", {}).get("agent_timeout_seconds")
        env = self.settings.get("extra_env") or {}

        is_orchestrator = self.role == "orchestrator"

        async def _run() -> None:
            try:
                await self.runner.start(self.workspace_path, full_prompt, extra_flags=extra_flags, env=env)
                collected: list[str] = []

                async for line, meta in self.runner.stream():
                    # Send tool-use notices as separate highlighted messages
                    if meta.get("tool_uses"):
                        for tu in meta["tool_uses"]:
                            await streamer.send_tool_notice(
                                tu["name"], tu["summary"], self.agent_id
                            )

                    if line is None:
                        await asyncio.sleep(0)
                        continue
                    if line.startswith("[session started"):
                        continue

                    # Orchestrator: intercept [[SOPHIA:...]] commands
                    if is_orchestrator and line:
                        from core.meta_commands import parse_commands, strip_commands, execute_command
                        cmds = parse_commands(line)
                        if cmds:
                            clean_line = strip_commands(line)
                            if clean_line:
                                await streamer.feed(clean_line)
                                collected.append(clean_line)
                            for cmd in cmds:
                                try:
                                    result = await execute_command(cmd, streamer.chat_id)
                                except Exception as e:
                                    result = f"❌ Command failed: {e}"
                                await streamer.send_orchestrator_notice(cmd["raw"], result)
                            await asyncio.sleep(0)
                            continue

                    await streamer.feed(line)
                    collected.append(line)

                    if bridge:
                        await bridge.broadcast(self.agent_id, self.name, line)
                        peer_msg = await bridge.receive(self.agent_id)
                        if peer_msg:
                            await self.runner.send_prompt(
                                f"[Peer:{peer_msg['sender_name']}] {peer_msg['content']}"
                            )

                    await asyncio.sleep(0)

                full_output = "\n".join(collected)
                await save_message(session_id, self.agent_id, "assistant", full_output)
                self.status = "done"
                await _update_status(self.agent_id, "done")
                await streamer.send_final("done")

            except asyncio.CancelledError:
                self.status = "idle"
                await _update_status(self.agent_id, "idle")
                await self.runner.stop()
                raise  # let wait_for convert this to TimeoutError when applicable

            except FileNotFoundError as e:
                await self._send_error(
                    streamer,
                    f"Could not start: <code>{e}</code>\n\n"
                    f"Check that <code>{self.workspace_path}</code> exists on this machine.",
                )

            except Exception as e:
                await self._send_error(streamer, f"Unexpected error: <code>{type(e).__name__}: {e}</code>")

            finally:
                if bridge:
                    bridge.unsubscribe(self.agent_id)

        try:
            if timeout_secs:
                await asyncio.wait_for(_run(), timeout=float(timeout_secs))
            else:
                await _run()
        except asyncio.TimeoutError:
            await self.runner.stop()
            self.status = "done"
            await _update_status(self.agent_id, "done")
            await streamer.send_final("timeout")
            try:
                await streamer.bot.send_message(
                    streamer.chat_id,
                    f"⏱ <b>[{self.name}]</b> Agent timed out after {timeout_secs}s and was stopped.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        except asyncio.CancelledError:
            pass

    def launch(self, prompt: str, streamer: AgentStreamer, resume: bool = False) -> asyncio.Task:
        self._task = asyncio.create_task(
            self.start(prompt, streamer, resume=resume), name=f"agent-{self.agent_id[:8]}"
        )
        return self._task

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self.runner:
            await self.runner.stop()

    async def kill(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        if self.runner:
            await self.runner.kill()

    async def inject_prompt(self, text: str) -> None:
        if self.runner and self.runner.is_running:
            await self.runner.send_prompt(text)


async def _update_status(agent_id: str, status: str) -> None:
    await db.execute(
        "UPDATE agents SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (status, agent_id),
    )
