"""Unit tests for streaming/streamer.py"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from streaming.streamer import AgentStreamer, _split_text


# ── _split_text ───────────────────────────────────────────────────────────────

def test_split_text_short():
    parts = _split_text("hello world", limit=4096)
    assert parts == ["hello world"]


def test_split_text_long():
    long = "word\n" * 2000  # ~10000 chars
    parts = _split_text(long, limit=4096)
    assert len(parts) > 1
    for p in parts:
        assert len(p) <= 4096


def test_split_text_no_newline():
    text = "x" * 5000
    parts = _split_text(text, limit=4096)
    assert len(parts) == 2
    assert len(parts[0]) == 4096


def test_split_text_exact_limit():
    text = "a" * 4096
    parts = _split_text(text, limit=4096)
    assert parts == [text]


# ── AgentStreamer ─────────────────────────────────────────────────────────────

def _make_streamer():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=42))
    bot.edit_message_text = AsyncMock()
    return AgentStreamer(bot, chat_id=12345, agent_name="TestAgent", chunk_lines=1)


@pytest.mark.asyncio
async def test_feed_triggers_flush_at_chunk_lines():
    s = _make_streamer()
    await s.feed("line one")
    s.bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_feed_accumulates_below_chunk_lines():
    s = AgentStreamer(
        MagicMock(
            send_message=AsyncMock(return_value=MagicMock(message_id=1)),
            edit_message_text=AsyncMock(),
        ),
        chat_id=1,
        agent_name="A",
        chunk_lines=3,
    )
    await s.feed("line1")
    await s.feed("line2")
    s.bot.send_message.assert_not_called()
    await s.feed("line3")
    s.bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_flush_empty_buffer():
    s = _make_streamer()
    await s.flush()
    s.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_second_flush_edits_existing_message():
    s = _make_streamer()
    await s.feed("first")
    await s.feed("second")
    assert s.bot.edit_message_text.called or s.bot.send_message.call_count == 2


@pytest.mark.asyncio
async def test_send_tool_notice_resets_state():
    s = _make_streamer()
    s._current_msg_id = 99
    s._current_text = "some text"

    with patch("bot.keyboards.kill_during_run_keyboard", return_value=None):
        await s.send_tool_notice("Bash", "echo hello", "agent-123")

    assert s._current_msg_id is None
    assert s._current_text == ""
    s.bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_send_orchestrator_notice_resets_state():
    s = _make_streamer()
    s._current_msg_id = 77
    s._current_text = "previous"

    await s.send_orchestrator_notice(
        '[[SOPHIA:CREATE_WORKSPACE name="p" path="/tmp/p"]]',
        "✅ Workspace <b>p</b> created"
    )

    assert s._current_msg_id is None
    assert s._current_text == ""
    s.bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_send_final_done():
    s = _make_streamer()
    await s.send_final("done")
    call_args = s.bot.send_message.call_args
    assert "✅" in call_args[0][1] or "done" in call_args[0][1].lower()


@pytest.mark.asyncio
async def test_send_final_flushes_buffer():
    s = _make_streamer()
    s._buffer = ["pending line"]
    s._current_msg_id = None
    await s.send_final("done")
    # Both flush and final message sent
    assert s.bot.send_message.call_count >= 1


@pytest.mark.asyncio
async def test_html_escape_in_tool_notice():
    s = _make_streamer()
    with patch("bot.keyboards.kill_during_run_keyboard", return_value=None):
        await s.send_tool_notice("Bash", "<dangerous> & stuff", "aid")
    text = s.bot.send_message.call_args[0][1]
    assert "<dangerous>" not in text
    assert "&lt;dangerous&gt;" in text
