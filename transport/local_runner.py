import asyncio
import json
import logging
import os
import re
from typing import AsyncIterator, Callable, Awaitable

log = logging.getLogger(__name__)

APPROVAL_PATTERNS = [
    re.compile(r"Do you want to (run|execute|proceed|allow|continue)", re.IGNORECASE),
    re.compile(r"\[y/n\]|\[Y/n\]|\(y/n\)", re.IGNORECASE),
    re.compile(r"Press Enter to (continue|confirm)", re.IGNORECASE),
    re.compile(r"Allow this action\?", re.IGNORECASE),
    # Claude Code native permission dialog patterns
    re.compile(r"blocked pending your approval", re.IGNORECASE),
    re.compile(r"Claude Code permission dialog", re.IGNORECASE),
    re.compile(r"bash is not allowed", re.IGNORECASE),
    re.compile(r"shell command.*approval", re.IGNORECASE),
]


def _needs_approval(line: str) -> bool:
    return any(p.search(line) for p in APPROVAL_PATTERNS)


def _summarise_tool_input(name: str, inp: dict) -> str:
    """Return a short human-readable summary of a tool call input."""
    if name == "Bash":
        cmd = inp.get("command", "")
        return cmd[:300]
    if name in ("Write", "Edit", "Read", "MultiEdit"):
        path = inp.get("file_path") or inp.get("path", "")
        return path
    return json.dumps(inp, ensure_ascii=False)[:200]


def _extract_text(raw: str) -> tuple[str | None, dict | None]:
    """Parse a stream-json line.

    Returns (text_or_None, metadata_or_None).
    metadata may contain:
      'session_id'  - from system.init
      'tool_uses'   - list of {name, summary} dicts from assistant events
    """
    raw = raw.strip()
    if not raw:
        return None, None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return (raw if raw else None), None

    t = obj.get("type")

    if t == "assistant":
        parts = []
        tool_uses = []
        for block in obj.get("message", {}).get("content", []):
            if block.get("type") == "text":
                parts.append(block["text"])
            elif block.get("type") == "tool_use":
                name = block.get("name", "tool")
                inp = block.get("input", {})
                summary = _summarise_tool_input(name, inp)
                tool_uses.append({"name": name, "summary": summary})
        meta = {"tool_uses": tool_uses} if tool_uses else None
        # Yield even when text is empty if there are tool_uses - agent.py needs the meta
        text = "\n".join(parts) if parts else None
        return text, meta

    if t == "result":
        meta: dict = {}
        usage = obj.get("usage")
        cost = obj.get("cost_usd")
        if usage:
            meta["usage"] = usage
        if cost is not None:
            meta["cost_usd"] = cost
        if obj.get("is_error"):
            return f"[error] {obj.get('result', '')}", meta or None
        return None, meta or None

    if t == "system" and obj.get("subtype") == "init":
        model = obj.get("model", "")
        sid = obj.get("session_id")
        meta: dict = {}
        if sid:
            meta["session_id"] = sid
        return f"[session started - model: {model}]", meta

    return None, None


class LocalRunner:
    def __init__(self, claude_path: str = "claude", default_flags: list[str] | None = None):
        self.claude_path = claude_path
        self.default_flags = default_flags or []
        self._proc: asyncio.subprocess.Process | None = None
        self._approval_cb: Callable[[str], Awaitable[bool]] | None = None
        self._session_id_cb: Callable[[str], Awaitable[None]] | None = None
        self.claude_session_id: str | None = None

    def set_approval_callback(self, cb: Callable[[str], Awaitable[bool]]) -> None:
        self._approval_cb = cb

    def set_session_id_callback(self, cb: Callable[[str], Awaitable[None]]) -> None:
        self._session_id_cb = cb

    async def start(
        self,
        workspace_path: str,
        prompt: str,
        extra_flags: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        flags = self.default_flags + (extra_flags or []) + [
            "-p", "--output-format", "stream-json", "--verbose"
        ]
        cmd = [self.claude_path] + flags + [prompt]
        proc_env = {**os.environ, **(env or {})}
        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=workspace_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=proc_env,
            limit=10 * 1024 * 1024,  # 10MB: Claude JSON lines can be very long
        )
        # Keep stdin open so we can respond to approval prompts and inject follow-up prompts.
        # The -p flag delivers the initial prompt via argv, not stdin, so leaving it open is safe.
        log.info("LocalRunner started PID=%d workspace=%s", self._proc.pid, workspace_path)

    async def stream(self) -> AsyncIterator[tuple[str, dict]]:
        """Yields (text, metadata) tuples.

        metadata may include 'tool_uses' and 'session_id' keys.
        """
        if self._proc is None:
            return
        assert self._proc.stdout is not None
        while True:
            try:
                line_bytes = await self._proc.stdout.readline()
            except (ConnectionResetError, asyncio.IncompleteReadError):
                break  # subprocess exited or pipe was reset
            if not line_bytes:
                break
            raw = line_bytes.decode("utf-8", errors="replace").rstrip()
            if _needs_approval(raw):
                approved = True
                if self._approval_cb:
                    approved = await self._approval_cb(raw)
                if self._proc.stdin:
                    try:
                        self._proc.stdin.write(("y\n" if approved else "n\n").encode())
                        await self._proc.stdin.drain()
                    except (BrokenPipeError, ConnectionResetError):
                        pass  # process exited before we could write the response
            text, meta = _extract_text(raw)
            meta = meta or {}
            if meta.get("session_id"):
                self.claude_session_id = meta["session_id"]
                if self._session_id_cb:
                    await self._session_id_cb(meta["session_id"])
            if text is not None or meta.get("tool_uses"):
                yield text, meta
        await self._proc.wait()

    async def send_prompt(self, text: str) -> None:
        if self._proc and self._proc.stdin:
            self._proc.stdin.write((text + "\n").encode())
            await self._proc.stdin.drain()

    async def stop(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._proc.kill()
            log.info("LocalRunner stopped PID=%d", self._proc.pid)

    async def kill(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.kill()
            await self._proc.wait()
            log.info("LocalRunner killed PID=%d", self._proc.pid)

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None
