import asyncio
import logging
import re
from typing import AsyncIterator, Callable, Awaitable

from transport.local_runner import _extract_text

try:
    import asyncssh
    HAS_ASYNCSSH = True
except ImportError:
    HAS_ASYNCSSH = False

log = logging.getLogger(__name__)

APPROVAL_PATTERNS = [
    re.compile(r"Do you want to (run|execute|proceed|allow|continue)", re.IGNORECASE),
    re.compile(r"\[y/n\]|\[Y/n\]|\(y/n\)", re.IGNORECASE),
    re.compile(r"Press Enter to (continue|confirm)", re.IGNORECASE),
    re.compile(r"Allow this action\?", re.IGNORECASE),
]


def _needs_approval(line: str) -> bool:
    return any(p.search(line) for p in APPROVAL_PATTERNS)


class SSHRunner:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        key_path: str | None = None,
        password: str | None = None,
        claude_path: str = "claude",
        default_flags: list[str] | None = None,
    ):
        if not HAS_ASYNCSSH:
            raise RuntimeError("asyncssh is not installed")
        self.host = host
        self.port = port
        self.username = username
        self.key_path = key_path
        self.password = password
        self.claude_path = claude_path
        self.default_flags = default_flags or []
        self._conn: "asyncssh.SSHClientConnection | None" = None
        self._process: "asyncssh.SSHClientProcess | None" = None
        self._approval_cb: Callable[[str], Awaitable[bool]] | None = None
        self._session_id_cb: Callable[[str], Awaitable[None]] | None = None
        self.claude_session_id: str | None = None

    def set_approval_callback(self, cb: Callable[[str], Awaitable[bool]]) -> None:
        self._approval_cb = cb

    def set_session_id_callback(self, cb: Callable[[str], Awaitable[None]]) -> None:
        self._session_id_cb = cb

    async def _connect(self) -> None:
        kwargs: dict = {
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "known_hosts": None,
            "keepalive_interval": 30,
        }
        if self.key_path:
            kwargs["client_keys"] = [self.key_path]
        if self.password:
            kwargs["password"] = self.password
        self._conn = await asyncssh.connect(**kwargs)
        log.info("SSH connected to %s@%s:%d", self.username, self.host, self.port)

    async def start(
        self,
        workspace_path: str,
        prompt: str,
        extra_flags: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        await self._connect()
        flags = self.default_flags + (extra_flags or []) + [
            "-p", "--output-format", "stream-json", "--verbose"
        ]
        safe_prompt = prompt.replace("'", "'\\''")
        env_prefix = " ".join(f"{k}={v}" for k, v in (env or {}).items())
        cmd = f"cd '{workspace_path}' && {env_prefix + ' ' if env_prefix else ''}{self.claude_path} {' '.join(flags)} '{safe_prompt}'"
        self._process = await self._conn.create_process(cmd)
        log.info("SSHRunner started on %s:%s", self.host, workspace_path)

    async def stream(self) -> AsyncIterator[tuple[str, dict]]:
        if self._process is None:
            return
        async for raw in self._process.stdout:
            raw = raw.rstrip()
            if _needs_approval(raw):
                approved = True
                if self._approval_cb:
                    approved = await self._approval_cb(raw)
                if self._process.stdin:
                    self._process.stdin.write("y\n" if approved else "n\n")
            text, meta = _extract_text(raw)
            meta = meta or {}
            if meta.get("session_id"):
                self.claude_session_id = meta["session_id"]
                if self._session_id_cb:
                    await self._session_id_cb(meta["session_id"])
            if text is not None or meta.get("tool_uses"):
                yield text, meta
        await self._process.wait()

    async def send_prompt(self, text: str) -> None:
        if self._process and self._process.stdin:
            self._process.stdin.write(text + "\n")

    async def stop(self) -> None:
        if self._process:
            self._process.terminate()
        if self._conn:
            self._conn.close()
            await self._conn.wait_closed()
        log.info("SSHRunner stopped for %s", self.host)

    async def kill(self) -> None:
        if self._process:
            self._process.kill()
        if self._conn:
            self._conn.close()
            await self._conn.wait_closed()

    async def test_connection(self) -> tuple[bool, str]:
        try:
            await self._connect()
            result = await self._conn.run("echo ok", check=True)
            self._conn.close()
            return True, result.stdout.strip()
        except Exception as e:
            return False, str(e)

    @property
    def is_running(self) -> bool:
        return self._process is not None and not self._process.returncode
