import asyncio
import logging
import re
from pathlib import Path
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

log = logging.getLogger(__name__)

_CODE_FENCE = re.compile(r"```")
MAX_MSG = 4096


def _split_text(text: str, limit: int = MAX_MSG) -> list[str]:
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


class AgentStreamer:
    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        agent_name: str,
        chunk_lines: int = 5,
    ):
        self.bot = bot
        self.chat_id = chat_id
        self.agent_name = agent_name
        self.chunk_lines = chunk_lines
        self._buffer: list[str] = []
        self._current_msg_id: int | None = None
        self._current_text = ""
        self._artifacts: list[str] = []
        self._in_code_block = False

    def _prefix(self) -> str:
        return f"🤖 [{self.agent_name}]\n"

    def _wrap(self, text: str) -> str:
        return self._prefix() + text

    async def feed(self, line: str) -> None:
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

        if len(self._wrap(new_text)) > MAX_MSG:
            await self._send_new(new_text)
            self._current_text = ""
            return

        if self._current_msg_id:
            try:
                await self.bot.edit_message_text(
                    self._wrap(new_text),
                    chat_id=self.chat_id,
                    message_id=self._current_msg_id,
                    parse_mode=None,
                )
                self._current_text = new_text
                return
            except TelegramBadRequest:
                pass

        await self._send_new(new_text)

    async def _send_new(self, text: str) -> None:
        for part in _split_text(text):
            try:
                msg = await self.bot.send_message(
                    self.chat_id,
                    self._wrap(part),
                    parse_mode=None,
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
                caption=f"🤖 [{self.agent_name}] {p.name}",
            )
            self._artifacts.append(file_path)
        except Exception as e:
            log.error("Failed to send artifact %s: %s", file_path, e)

    async def send_tool_notice(self, tool_name: str, summary: str, agent_id: str) -> None:
        """Send a distinct message when Claude is about to use a tool."""
        from html import escape
        from bot.keyboards import kill_during_run_keyboard
        sensitive = tool_name.lower() in ("bash", "computer", "repl", "exec")
        icon = "⚡" if sensitive else "🔧"
        text = (
            f"{icon} <b>[{escape(self.agent_name)}]</b> - <b>{escape(tool_name)}</b>\n"
            f"<code>{escape(summary[:300])}</code>"
        )
        try:
            await self.bot.send_message(
                self.chat_id,
                text,
                parse_mode="HTML",
                reply_markup=kill_during_run_keyboard(agent_id),
            )
            # Reset so next content flush sends a new message below the tool notice
            self._current_msg_id = None
            self._current_text = ""
        except Exception as e:
            log.error("Failed to send tool notice: %s", e)

    async def send_orchestrator_notice(self, command_raw: str, result: str) -> None:
        """Send feedback when Sophia executes a SOPHIA command."""
        from html import escape
        text = (
            f"🎭 <b>[{escape(self.agent_name)}]</b>\n"
            f"<code>{escape(command_raw)}</code>\n\n"
            f"{result}"
        )
        try:
            await self.bot.send_message(self.chat_id, text, parse_mode="HTML")
            self._current_msg_id = None
            self._current_text = ""
        except Exception as e:
            log.error("Failed to send orchestrator notice: %s", e)

    async def send_final(self, status: str) -> None:
        from html import escape
        await self.flush()
        icon_map = {"done": "✅", "timeout": "⏱", "error": "❌"}
        emoji = icon_map.get(status, "❌")
        try:
            await self.bot.send_message(
                self.chat_id,
                f"{emoji} <b>[{escape(self.agent_name)}]</b> {status}.",
                parse_mode="HTML",
            )
        except Exception as e:
            log.error("Failed to send final message: %s", e)
