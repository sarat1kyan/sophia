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
