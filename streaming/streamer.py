import asyncio
import logging
import re
from html import escape
from pathlib import Path
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

log = logging.getLogger(__name__)

_CODE_FENCE = re.compile(r"```")
_FENCE_BLOCK = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
MAX_MSG = 3800  # safe margin below Telegram's 4096


def _split_plain(text: str, limit: int = MAX_MSG) -> list[str]:
    chunks = []
    while len(text) > limit:
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


def _format_text(text: str) -> tuple[str, str | None]:
    """Convert complete markdown code fences to Telegram HTML <pre><code>.
    Always returns HTML parse mode with properly escaped content."""
    if "```" not in text or text.count("```") % 2 != 0:
        return escape(text), "HTML"
    result = []
    last = 0
    for m in _FENCE_BLOCK.finditer(text):
        before = text[last:m.start()]
        if before:
            result.append(escape(before))
        code = m.group(2)
        result.append(f"<pre><code>{escape(code)}</code></pre>")
        last = m.end()
    tail = text[last:]
    if tail:
        result.append(escape(tail))
    return "".join(result), "HTML"


class AgentStreamer:
    """
    Streams Claude output to Telegram.

    mode="full"   - stream all text + tool notices (default for regular agents)
    mode="tools"  - tool notices only, text is suppressed (default for orchestrators)
    mode="silent" - nothing until final status
    """

    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        agent_name: str,
        chunk_lines: int = 1,
        mode: str = "full",
    ):
        self.bot = bot
        self.chat_id = chat_id
        self.agent_name = agent_name
        self.chunk_lines = chunk_lines
        self.mode = mode
        self._buffer: list[str] = []
        self._current_msg_id: int | None = None
        self._current_text = ""
        self._in_code_block = False
        self._artifacts: list[str] = []
        # Tools-mode compact board
        self._activity_msg_id: int | None = None
        self._tool_count: int = 0

    def _prefix(self) -> str:
        return f"🤖 <b>{escape(self.agent_name)}</b>\n"

    async def feed(self, line: str) -> None:
        if self.mode != "full":
            return
        fences = len(_CODE_FENCE.findall(line))
        if fences % 2 != 0:
            self._in_code_block = not self._in_code_block
        self._buffer.append(line)
        if len(self._buffer) >= self.chunk_lines or (not self._in_code_block and line == ""):
            await self.flush()

    async def flush(self) -> None:
        if not self._buffer:
            return
        chunk = "\n".join(self._buffer)
        self._buffer = []
        new_text = (self._current_text + "\n" + chunk).strip() if self._current_text else chunk

        wrapped_len = len(self._prefix()) + len(new_text)
        if wrapped_len > MAX_MSG:
            await self._send_new(new_text)
            self._current_text = ""
            return

        if self._current_msg_id:
            try:
                formatted, parse_mode = _format_text(new_text)
                full_msg = self._prefix() + formatted
                await self.bot.edit_message_text(
                    full_msg,
                    chat_id=self.chat_id,
                    message_id=self._current_msg_id,
                    parse_mode=parse_mode or "HTML",
                )
                self._current_text = new_text
                return
            except TelegramBadRequest:
                pass

        await self._send_new(new_text)

    async def _send_new(self, text: str) -> None:
        for part in _split_plain(text):
            try:
                formatted, parse_mode = _format_text(part)
                msg = await self.bot.send_message(
                    self.chat_id,
                    self._prefix() + formatted,
                    parse_mode=parse_mode or "HTML",
                )
                self._current_msg_id = msg.message_id
                self._current_text = part
            except Exception as e:
                log.error("Failed to send message: %s", e)

    async def send_artifact(self, file_path: str) -> None:
        p = Path(file_path)
        if not p.exists():
            return
        try:
            from aiogram.types import FSInputFile
            doc = FSInputFile(file_path, filename=p.name)
            await self.bot.send_document(
                self.chat_id,
                doc,
                caption=f"🤖 <b>[{escape(self.agent_name)}]</b> {p.name}",
                parse_mode="HTML",
            )
            self._artifacts.append(file_path)
        except Exception as e:
            log.error("Failed to send artifact %s: %s", file_path, e)

    async def send_agent_start(self) -> None:
        """Send a 'starting' card; in tools mode it becomes the activity board."""
        if self.mode == "silent":
            return
        try:
            text = f"⚙️ <b>{escape(self.agent_name)}</b>  <i>starting…</i>"
            msg = await self.bot.send_message(self.chat_id, text, parse_mode="HTML")
            if self.mode == "tools":
                self._activity_msg_id = msg.message_id
        except Exception as e:
            log.error("Failed to send agent start: %s", e)

    async def send_tool_notice(self, tool_name: str, summary: str, agent_id: str) -> None:
        if self.mode == "silent":
            return
        from bot.keyboards import kill_during_run_keyboard
        sensitive = tool_name.lower() in ("bash", "computer", "repl", "exec")
        icon = "⚡" if sensitive else "🔧"

        if self.mode == "tools":
            self._tool_count += 1
            short = summary[:200]
            text = (
                f"⚙️ <b>{escape(self.agent_name)}</b>"
                f"  ·  <i>step {self._tool_count}</i>\n"
                f"──────────────────\n"
                f"{icon} <b>{escape(tool_name)}</b>\n"
                f"<code>{escape(short)}</code>"
            )
            if self._activity_msg_id:
                try:
                    await self.bot.edit_message_text(
                        text,
                        chat_id=self.chat_id,
                        message_id=self._activity_msg_id,
                        parse_mode="HTML",
                        reply_markup=kill_during_run_keyboard(agent_id),
                    )
                    return
                except TelegramBadRequest:
                    self._activity_msg_id = None
            try:
                msg = await self.bot.send_message(
                    self.chat_id, text, parse_mode="HTML",
                    reply_markup=kill_during_run_keyboard(agent_id),
                )
                self._activity_msg_id = msg.message_id
            except Exception as e:
                log.error("Failed to send tool notice: %s", e)
            return

        # full mode: one message per tool call
        text = (
            f"{icon} <b>{escape(self.agent_name)}</b>  ·  <b>{escape(tool_name)}</b>\n"
            f"<code>{escape(summary[:300])}</code>"
        )
        try:
            await self.bot.send_message(
                self.chat_id,
                text,
                parse_mode="HTML",
                reply_markup=kill_during_run_keyboard(agent_id),
            )
            self._current_msg_id = None
            self._current_text = ""
        except Exception as e:
            log.error("Failed to send tool notice: %s", e)

    async def send_orchestrator_notice(self, cmd_type: str, cmd_args: dict, result: str) -> None:
        """Structured status card for each Sophia orchestration action."""
        icons = {
            "CREATE_WORKSPACE": "📁",
            "CREATE_AGENT": "🤖",
            "RUN_AGENT": "▶️",
            "LIST_AGENTS": "📋",
            "LIST_WORKSPACES": "🗂",
        }
        labels = {
            "CREATE_WORKSPACE": "New Workspace",
            "CREATE_AGENT": "New Agent",
            "RUN_AGENT": "Starting Agent",
            "LIST_AGENTS": "List Agents",
            "LIST_WORKSPACES": "List Workspaces",
        }
        icon = icons.get(cmd_type, "🔧")
        label = labels.get(cmd_type, cmd_type)
        sep = "──────────────────"

        body_lines = [result]
        if cmd_type == "CREATE_WORKSPACE":
            path = cmd_args.get("path", "")
            if path:
                body_lines.append(f"<code>{escape(path)}</code>")
        elif cmd_type == "CREATE_AGENT":
            parts = []
            role = cmd_args.get("role", "")
            tpl  = cmd_args.get("template", "")
            ws   = cmd_args.get("workspace", "")
            if role:
                parts.append(f"role: {escape(role)}")
            if tpl and tpl != role:
                parts.append(f"template: {escape(tpl)}")
            if ws:
                parts.append(f"workspace: {escape(ws)}")
            if parts:
                body_lines.append(f"<i>{' · '.join(parts)}</i>")
        elif cmd_type == "RUN_AGENT":
            prompt = cmd_args.get("prompt", "")
            if prompt:
                preview = prompt[:100].replace("\n", " ")
                body_lines.append(
                    f"<i>{escape(preview)}{'…' if len(prompt) > 100 else ''}</i>"
                )

        text = (
            f"🎭 <b>Sophia</b>  ·  {icon} {label}\n"
            f"{sep}\n"
            + "\n".join(body_lines)
        )
        try:
            await self.bot.send_message(self.chat_id, text, parse_mode="HTML")
            self._current_msg_id = None
            self._current_text = ""
        except Exception as e:
            log.error("Failed to send orchestrator notice: %s", e)

    async def send_final(
        self,
        status: str,
        usage: dict | None = None,
        cost: float | None = None,
    ) -> None:
        await self.flush()
        icon_map = {"done": "✅", "timeout": "⏱", "error": "❌"}
        emoji = icon_map.get(status, "❌")
        sep = "━" * 22

        parts = [
            sep,
            f"{emoji}  <b>{escape(self.agent_name)}</b>  ·  {status}",
            sep,
        ]
        if usage:
            inp    = usage.get("input_tokens", 0)
            out    = usage.get("output_tokens", 0)
            cached = usage.get("cache_read_input_tokens", 0)
            if inp or out:
                parts.append(f"📥 in {inp:,}  ·  📤 out {out:,}")
                if cached:
                    parts.append(f"⚡ {cached:,} cached")
                if cost is not None:
                    parts.append(f"💰 ${cost:.4f}")

        try:
            await self.bot.send_message(
                self.chat_id,
                "\n".join(parts),
                parse_mode="HTML",
            )
        except Exception as e:
            log.error("Failed to send final message: %s", e)
