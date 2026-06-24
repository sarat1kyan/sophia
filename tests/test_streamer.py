"""Unit tests for streaming/streamer.py"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from streaming.streamer import AgentStreamer, _split_plain, _format_text


# ── _split_plain ──────────────────────────────────────────────────────────────

def test_split_text_short():
    parts = _split_plain("hello world", limit=4096)
    assert parts == ["hello world"]


def test_split_text_long():
    long = "word\n" * 2000  # ~10000 chars
    parts = _split_plain(long, limit=4096)
    assert len(parts) > 1
    for p in parts:
        assert len(p) <= 4096


def test_split_text_no_newline():
    text = "x" * 5000
    parts = _split_plain(text, limit=4096)
    assert len(parts) == 2
    assert len(parts[0]) == 4096


def test_split_text_exact_limit():
    text = "a" * 4096
    parts = _split_plain(text, limit=4096)
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
        "CREATE_WORKSPACE",
        {"name": "p", "path": "/tmp/p"},
        "✅ Workspace p created",
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


# ── _format_text ──────────────────────────────────────────────────────────────

def test_format_text_plain_no_fences():
    html, mode = _format_text("hello world")
    assert html == "hello world"
    assert mode == "HTML"

def test_format_text_escapes_html_chars():
    html, mode = _format_text("a < b & c > d")
    assert "&lt;" in html
    assert "&amp;" in html
    assert "&gt;" in html
    assert mode == "HTML"

def test_format_text_odd_fence_count_returns_escaped():
    # Single ``` (odd count) → everything escaped, no code block
    html, mode = _format_text("start ``` end")
    assert "<pre>" not in html
    assert mode == "HTML"

def test_format_text_complete_fence_wraps_in_pre():
    html, mode = _format_text("```python\nprint('hi')\n```")
    assert "<pre><code>" in html
    assert "</code></pre>" in html
    assert mode == "HTML"

def test_format_text_html_in_code_block_escaped():
    html, mode = _format_text("```\n<script>alert(1)</script>\n```")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html

def test_format_text_text_around_fence():
    html, mode = _format_text("before\n```\ncode\n```\nafter")
    assert "before" in html
    assert "after" in html
    assert "<pre><code>" in html

def test_format_text_three_fences_odd_escapes_all():
    html, mode = _format_text("```a\ncode1\n``` middle ```")
    assert "<pre>" not in html


# ── send_agent_start ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_agent_start_tools_mode_sets_activity_id():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=55))
    s = AgentStreamer(bot, chat_id=1, agent_name="Bot", mode="tools")
    await s.send_agent_start()
    bot.send_message.assert_called_once()
    assert s._activity_msg_id == 55

@pytest.mark.asyncio
async def test_send_agent_start_full_mode_no_activity_id():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=77))
    s = AgentStreamer(bot, chat_id=1, agent_name="Bot", mode="full")
    await s.send_agent_start()
    bot.send_message.assert_called_once()
    assert s._activity_msg_id is None  # full mode does not use activity board

@pytest.mark.asyncio
async def test_send_agent_start_silent_mode_no_message():
    bot = MagicMock()
    bot.send_message = AsyncMock()
    s = AgentStreamer(bot, chat_id=1, agent_name="Bot", mode="silent")
    await s.send_agent_start()
    bot.send_message.assert_not_called()

@pytest.mark.asyncio
async def test_send_agent_start_then_tool_notice_edits_start_message():
    """tools mode: start msg is set as activity board, first tool notice should EDIT it."""
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=99))
    bot.edit_message_text = AsyncMock()
    s = AgentStreamer(bot, chat_id=1, agent_name="A", mode="tools")
    await s.send_agent_start()
    assert s._activity_msg_id == 99
    with patch("bot.keyboards.kill_during_run_keyboard", return_value=None):
        await s.send_tool_notice("Bash", "ls", "aid")
    bot.edit_message_text.assert_called_once()
    assert bot.edit_message_text.call_args[1]["message_id"] == 99
    assert bot.send_message.call_count == 1  # only the start message itself


# ── send_tool_notice additional ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_tool_notice_silent_does_nothing():
    bot = MagicMock()
    bot.send_message = AsyncMock()
    s = AgentStreamer(bot, chat_id=1, agent_name="X", mode="silent")
    await s.send_tool_notice("Bash", "ls", "aid")
    bot.send_message.assert_not_called()

@pytest.mark.asyncio
async def test_send_tool_notice_tools_mode_first_call_sends_new():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=10))
    bot.edit_message_text = AsyncMock()
    s = AgentStreamer(bot, chat_id=1, agent_name="X", mode="tools")
    with patch("bot.keyboards.kill_during_run_keyboard", return_value=None):
        await s.send_tool_notice("Write", "foo.py", "aid")
    bot.send_message.assert_called_once()
    assert s._activity_msg_id == 10

@pytest.mark.asyncio
async def test_send_tool_notice_tools_mode_second_call_edits():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=10))
    bot.edit_message_text = AsyncMock()
    s = AgentStreamer(bot, chat_id=1, agent_name="X", mode="tools")
    with patch("bot.keyboards.kill_during_run_keyboard", return_value=None):
        await s.send_tool_notice("Write", "foo.py", "aid")
        await s.send_tool_notice("Bash", "ls", "aid")
    assert bot.send_message.call_count == 1
    bot.edit_message_text.assert_called_once()

@pytest.mark.asyncio
async def test_send_tool_notice_tools_mode_stale_id_recovers():
    """TelegramBadRequest on edit → clears activity_msg_id, sends new message."""
    from aiogram.exceptions import TelegramBadRequest
    err = TelegramBadRequest.__new__(TelegramBadRequest)
    Exception.__init__(err, "message to edit not found")
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=20))
    bot.edit_message_text = AsyncMock(side_effect=err)
    s = AgentStreamer(bot, chat_id=1, agent_name="X", mode="tools")
    s._activity_msg_id = 999  # stale id
    with patch("bot.keyboards.kill_during_run_keyboard", return_value=None):
        await s.send_tool_notice("Bash", "ls", "aid")
    bot.send_message.assert_called_once()
    assert s._activity_msg_id == 20

@pytest.mark.asyncio
async def test_send_tool_notice_tools_mode_increments_counter():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    bot.edit_message_text = AsyncMock()
    s = AgentStreamer(bot, chat_id=1, agent_name="X", mode="tools")
    with patch("bot.keyboards.kill_during_run_keyboard", return_value=None):
        await s.send_tool_notice("Write", "a.py", "aid")
        await s.send_tool_notice("Write", "b.py", "aid")
        await s.send_tool_notice("Bash", "ls", "aid")
    assert s._tool_count == 3

@pytest.mark.asyncio
async def test_send_tool_notice_step_number_in_text():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    bot.edit_message_text = AsyncMock()
    s = AgentStreamer(bot, chat_id=1, agent_name="X", mode="tools")
    with patch("bot.keyboards.kill_during_run_keyboard", return_value=None):
        await s.send_tool_notice("Bash", "pwd", "aid")
    # After first send, subsequent edits contain the step number
    with patch("bot.keyboards.kill_during_run_keyboard", return_value=None):
        await s.send_tool_notice("Bash", "ls", "aid")
    edit_text = bot.edit_message_text.call_args[0][0]
    assert "step 2" in edit_text


# ── send_orchestrator_notice additional ──────────────────────────────────────

@pytest.mark.asyncio
async def test_send_orchestrator_notice_create_agent_includes_meta():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    s = AgentStreamer(bot, chat_id=1, agent_name="Sophia", mode="tools")
    await s.send_orchestrator_notice(
        "CREATE_AGENT",
        {"name": "Dev", "role": "coder", "workspace": "myproj"},
        "✅ Agent Dev [coder] created",
    )
    text = bot.send_message.call_args[0][1]
    assert "New Agent" in text
    assert "coder" in text
    assert "myproj" in text

@pytest.mark.asyncio
async def test_send_orchestrator_notice_run_agent_long_prompt_truncated():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    s = AgentStreamer(bot, chat_id=1, agent_name="Sophia", mode="tools")
    await s.send_orchestrator_notice(
        "RUN_AGENT",
        {"name": "Dev", "prompt": "x" * 200},
        "🚀 Agent Dev started",
    )
    text = bot.send_message.call_args[0][1]
    assert "…" in text

@pytest.mark.asyncio
async def test_send_orchestrator_notice_run_agent_short_prompt_no_ellipsis():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    s = AgentStreamer(bot, chat_id=1, agent_name="Sophia", mode="tools")
    await s.send_orchestrator_notice(
        "RUN_AGENT",
        {"name": "Dev", "prompt": "Short task"},
        "🚀 Agent Dev started",
    )
    text = bot.send_message.call_args[0][1]
    assert "…" not in text
    assert "Short task" in text

@pytest.mark.asyncio
async def test_send_orchestrator_notice_list_agents():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    s = AgentStreamer(bot, chat_id=1, agent_name="Sophia", mode="tools")
    await s.send_orchestrator_notice("LIST_AGENTS", {}, "📋 No agents found.")
    text = bot.send_message.call_args[0][1]
    assert "List Agents" in text

@pytest.mark.asyncio
async def test_send_orchestrator_notice_unknown_type_uses_fallback():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    s = AgentStreamer(bot, chat_id=1, agent_name="Sophia", mode="tools")
    await s.send_orchestrator_notice("MAGIC_CMD", {}, "some result")
    text = bot.send_message.call_args[0][1]
    assert "MAGIC_CMD" in text
    assert "🔧" in text

@pytest.mark.asyncio
async def test_send_orchestrator_notice_create_workspace_includes_path():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    s = AgentStreamer(bot, chat_id=1, agent_name="Sophia", mode="tools")
    await s.send_orchestrator_notice(
        "CREATE_WORKSPACE",
        {"name": "p", "path": "/workspaces/p"},
        "✅ Workspace p created",
    )
    text = bot.send_message.call_args[0][1]
    assert "/workspaces/p" in text
    assert "New Workspace" in text


# ── send_final additional ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_final_error_uses_red_x():
    s = _make_streamer()
    await s.send_final("error")
    text = s.bot.send_message.call_args[0][1]
    assert "❌" in text

@pytest.mark.asyncio
async def test_send_final_timeout_uses_clock():
    s = _make_streamer()
    await s.send_final("timeout")
    text = s.bot.send_message.call_args[0][1]
    assert "⏱" in text

@pytest.mark.asyncio
async def test_send_final_no_usage_no_token_lines():
    s = _make_streamer()
    await s.send_final("done", usage=None, cost=None)
    text = s.bot.send_message.call_args[0][1]
    assert "📥" not in text
    assert "💰" not in text

@pytest.mark.asyncio
async def test_send_final_with_cached_tokens_shows_cache_line():
    s = _make_streamer()
    await s.send_final(
        "done",
        usage={"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 80},
        cost=0.01,
    )
    text = s.bot.send_message.call_args[0][1]
    assert "⚡" in text
    assert "80" in text
    assert "💰" in text

@pytest.mark.asyncio
async def test_send_final_zero_cached_no_cache_line():
    s = _make_streamer()
    await s.send_final(
        "done",
        usage={"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0},
        cost=None,
    )
    text = s.bot.send_message.call_args[0][1]
    assert "⚡" not in text

@pytest.mark.asyncio
async def test_send_final_heavy_separator_in_text():
    s = _make_streamer()
    await s.send_final("done")
    text = s.bot.send_message.call_args[0][1]
    assert "━" in text

@pytest.mark.asyncio
async def test_send_final_agent_name_in_text():
    s = _make_streamer()
    await s.send_final("done")
    text = s.bot.send_message.call_args[0][1]
    assert "TestAgent" in text

@pytest.mark.asyncio
async def test_send_final_zero_tokens_suppresses_token_line():
    """Auth failure returns usage={in:0, out:0} — must NOT show '📥 in 0'."""
    s = _make_streamer()
    await s.send_final("error", usage={"input_tokens": 0, "output_tokens": 0}, cost=None)
    text = s.bot.send_message.call_args[0][1]
    assert "📥" not in text
    assert "📤" not in text

@pytest.mark.asyncio
async def test_send_final_nonzero_tokens_shows_token_line():
    s = _make_streamer()
    await s.send_final("done", usage={"input_tokens": 1500, "output_tokens": 300})
    text = s.bot.send_message.call_args[0][1]
    assert "1,500" in text
    assert "300" in text


# ── feed() mode filtering ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_feed_tools_mode_no_message_sent():
    bot = MagicMock()
    bot.send_message = AsyncMock()
    s = AgentStreamer(bot, chat_id=1, agent_name="X", mode="tools")
    await s.feed("some text line")
    bot.send_message.assert_not_called()

@pytest.mark.asyncio
async def test_feed_silent_mode_no_message_sent():
    bot = MagicMock()
    bot.send_message = AsyncMock()
    s = AgentStreamer(bot, chat_id=1, agent_name="X", mode="silent")
    await s.feed("some text line")
    bot.send_message.assert_not_called()


# ── _prefix no brackets ───────────────────────────────────────────────────────

def test_prefix_has_no_square_brackets():
    s = _make_streamer()
    prefix = s._prefix()
    assert "[" not in prefix
    assert "]" not in prefix
    assert "TestAgent" in prefix
