"""Unit tests for transport/local_runner.py - stream-json parsing."""
import pytest
import json

from transport.local_runner import _extract_text, _summarise_tool_input, _needs_approval


# ── _needs_approval ───────────────────────────────────────────────────────────

def test_needs_approval_yn():
    assert _needs_approval("Do you want to run this? [y/n]")


def test_needs_approval_allow():
    assert _needs_approval("Allow this action?")


def test_needs_approval_no_match():
    assert not _needs_approval("Just a regular line of output.")


# ── _summarise_tool_input ─────────────────────────────────────────────────────

def test_summarise_bash():
    assert _summarise_tool_input("Bash", {"command": "ls -la"}) == "ls -la"


def test_summarise_write():
    assert _summarise_tool_input("Write", {"file_path": "/tmp/foo.py"}) == "/tmp/foo.py"


def test_summarise_read():
    assert _summarise_tool_input("Read", {"file_path": "/etc/hosts"}) == "/etc/hosts"


def test_summarise_unknown_tool():
    result = _summarise_tool_input("UnknownTool", {"key": "value"})
    assert "value" in result


def test_summarise_bash_truncates():
    long_cmd = "x" * 400
    result = _summarise_tool_input("Bash", {"command": long_cmd})
    assert len(result) <= 300


# ── _extract_text ─────────────────────────────────────────────────────────────

def test_extract_empty_line():
    text, meta = _extract_text("")
    assert text is None
    assert meta is None


def test_extract_assistant_text():
    payload = json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "Hello!"}]}
    })
    text, meta = _extract_text(payload)
    assert text == "Hello!"
    assert meta is None


def test_extract_assistant_tool_use():
    payload = json.dumps({
        "type": "assistant",
        "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}
        ]}
    })
    text, meta = _extract_text(payload)
    assert text is None
    assert meta is not None
    assert len(meta["tool_uses"]) == 1
    assert meta["tool_uses"][0]["name"] == "Bash"
    assert meta["tool_uses"][0]["summary"] == "ls"


def test_extract_assistant_text_and_tool():
    payload = json.dumps({
        "type": "assistant",
        "message": {"content": [
            {"type": "text", "text": "Running..."},
            {"type": "tool_use", "name": "Write", "input": {"file_path": "/tmp/f.py"}}
        ]}
    })
    text, meta = _extract_text(payload)
    assert text == "Running..."
    assert meta["tool_uses"][0]["name"] == "Write"


def test_extract_result_no_error():
    payload = json.dumps({"type": "result", "is_error": False, "result": "ok"})
    text, meta = _extract_text(payload)
    assert text is None


def test_extract_result_error():
    payload = json.dumps({"type": "result", "is_error": True, "result": "boom"})
    text, meta = _extract_text(payload)
    assert text is not None
    assert "error" in text.lower() or "boom" in text


def test_extract_system_init():
    payload = json.dumps({
        "type": "system",
        "subtype": "init",
        "model": "claude-opus-4",
        "session_id": "abc-123"
    })
    text, meta = _extract_text(payload)
    assert text is not None
    assert "session started" in text
    assert meta["session_id"] == "abc-123"


def test_extract_invalid_json_returns_raw():
    text, meta = _extract_text("not json at all")
    assert text == "not json at all"
    assert meta is None


def test_extract_unknown_type_returns_none():
    payload = json.dumps({"type": "unknown_future_type", "data": "x"})
    text, meta = _extract_text(payload)
    assert text is None


# ── _needs_approval additional patterns ──────────────────────────────────────

def test_needs_approval_blocked_pending():
    assert _needs_approval("The shell commands are blocked pending your approval")

def test_needs_approval_bash_not_allowed():
    assert _needs_approval("bash is not allowed in the current configuration")

def test_needs_approval_shell_command_approval():
    assert _needs_approval("This shell command requires approval before running")

def test_needs_approval_press_enter():
    assert _needs_approval("Press Enter to continue with this operation")

def test_needs_approval_claude_code_dialog():
    assert _needs_approval("Claude Code permission dialog is waiting")

def test_needs_approval_do_you_want():
    assert _needs_approval("Do you want to execute this command?")


# ── _summarise_tool_input additional ──────────────────────────────────────────

def test_summarise_edit_returns_path():
    assert _summarise_tool_input("Edit", {"file_path": "/tmp/x.py"}) == "/tmp/x.py"

def test_summarise_multiedit_returns_path():
    assert _summarise_tool_input("MultiEdit", {"file_path": "/tmp/y.py"}) == "/tmp/y.py"

def test_summarise_unknown_tool_long_input_truncated():
    long_input = {"key": "v" * 300}
    result = _summarise_tool_input("FutureTool", long_input)
    assert len(result) <= 200


# ── _extract_text additional ──────────────────────────────────────────────────

def test_extract_result_with_usage():
    payload = json.dumps({
        "type": "result",
        "is_error": False,
        "usage": {"input_tokens": 100, "output_tokens": 50},
    })
    text, meta = _extract_text(payload)
    assert text is None
    assert meta is not None
    assert meta["usage"]["input_tokens"] == 100
    assert meta["usage"]["output_tokens"] == 50

def test_extract_result_with_cost():
    payload = json.dumps({
        "type": "result",
        "is_error": False,
        "cost_usd": 0.0124,
    })
    text, meta = _extract_text(payload)
    assert meta is not None
    assert abs(meta["cost_usd"] - 0.0124) < 0.0001

def test_extract_result_error_with_usage():
    payload = json.dumps({
        "type": "result",
        "is_error": True,
        "result": "Something failed",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    })
    text, meta = _extract_text(payload)
    assert "error" in text.lower() or "Something failed" in text
    assert meta["usage"]["input_tokens"] == 10

def test_extract_system_init_no_session_id():
    payload = json.dumps({
        "type": "system",
        "subtype": "init",
        "model": "claude-sonnet-4-6",
    })
    text, meta = _extract_text(payload)
    assert text is not None
    assert "session started" in text
    assert meta == {}  # empty dict, no session_id key

def test_extract_system_non_init_subtype_returns_none():
    payload = json.dumps({"type": "system", "subtype": "heartbeat"})
    text, meta = _extract_text(payload)
    assert text is None
    assert meta is None

def test_extract_assistant_empty_content_returns_none():
    payload = json.dumps({
        "type": "assistant",
        "message": {"content": []},
    })
    text, meta = _extract_text(payload)
    assert text is None
    assert meta is None

def test_extract_assistant_multiple_text_blocks_joined():
    payload = json.dumps({
        "type": "assistant",
        "message": {"content": [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": "World"},
        ]},
    })
    text, meta = _extract_text(payload)
    assert text == "Hello\nWorld"
