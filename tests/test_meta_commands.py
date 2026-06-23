"""Unit tests for core/meta_commands.py - Sophia command parsing."""
import pytest
from core.meta_commands import parse_commands, strip_commands


# ── parse_commands ────────────────────────────────────────────────────────────

def test_parse_single_create_workspace():
    text = '[[SOPHIA:CREATE_WORKSPACE name="myproject" path="/workspaces/myproject"]]'
    cmds = parse_commands(text)
    assert len(cmds) == 1
    assert cmds[0]["type"] == "CREATE_WORKSPACE"
    assert cmds[0]["args"]["name"] == "myproject"
    assert cmds[0]["args"]["path"] == "/workspaces/myproject"


def test_parse_create_agent():
    text = '[[SOPHIA:CREATE_AGENT name="Coder" role="coder" template="Coder" workspace="myproject"]]'
    cmds = parse_commands(text)
    assert len(cmds) == 1
    assert cmds[0]["type"] == "CREATE_AGENT"
    assert cmds[0]["args"]["name"] == "Coder"
    assert cmds[0]["args"]["role"] == "coder"
    assert cmds[0]["args"]["template"] == "Coder"
    assert cmds[0]["args"]["workspace"] == "myproject"


def test_parse_run_agent():
    text = '[[SOPHIA:RUN_AGENT name="Coder" prompt="Build a REST API with FastAPI"]]'
    cmds = parse_commands(text)
    assert len(cmds) == 1
    assert cmds[0]["type"] == "RUN_AGENT"
    assert cmds[0]["args"]["name"] == "Coder"
    assert cmds[0]["args"]["prompt"] == "Build a REST API with FastAPI"


def test_parse_multiple_commands_in_text():
    text = (
        "Let me set this up.\n"
        '[[SOPHIA:CREATE_WORKSPACE name="proj" path="/workspaces/proj"]]\n'
        "Now creating agent.\n"
        '[[SOPHIA:CREATE_AGENT name="Dev" role="coder" template="Coder" workspace="proj"]]\n'
        "Done!"
    )
    cmds = parse_commands(text)
    assert len(cmds) == 2
    assert cmds[0]["type"] == "CREATE_WORKSPACE"
    assert cmds[1]["type"] == "CREATE_AGENT"


def test_parse_no_commands():
    text = "This is just regular text with no commands."
    cmds = parse_commands(text)
    assert cmds == []


def test_parse_list_agents():
    text = "[[SOPHIA:LIST_AGENTS]]"
    cmds = parse_commands(text)
    assert len(cmds) == 1
    assert cmds[0]["type"] == "LIST_AGENTS"
    assert cmds[0]["args"] == {}


def test_parse_list_workspaces():
    text = "[[SOPHIA:LIST_WORKSPACES]]"
    cmds = parse_commands(text)
    assert len(cmds) == 1
    assert cmds[0]["type"] == "LIST_WORKSPACES"


def test_parse_preserves_raw():
    raw = '[[SOPHIA:CREATE_WORKSPACE name="x" path="/tmp/x"]]'
    cmds = parse_commands(raw)
    assert cmds[0]["raw"] == raw


def test_parse_skip_permissions_false():
    text = '[[SOPHIA:CREATE_AGENT name="Safe" role="tester" template="Tester" workspace="p" skip_permissions="false"]]'
    cmds = parse_commands(text)
    assert cmds[0]["args"]["skip_permissions"] == "false"


def test_parse_command_case_insensitive_type():
    # type is uppercased by the parser
    text = '[[SOPHIA:create_workspace name="x" path="/tmp/x"]]'
    cmds = parse_commands(text)
    assert cmds[0]["type"] == "CREATE_WORKSPACE"


# ── strip_commands ────────────────────────────────────────────────────────────

def test_strip_removes_command():
    text = 'Hello [[SOPHIA:LIST_AGENTS]] world'
    assert strip_commands(text) == "Hello  world"


def test_strip_removes_multiple():
    text = (
        '[[SOPHIA:CREATE_WORKSPACE name="p" path="/tmp/p"]]\n'
        'Some explanation\n'
        '[[SOPHIA:LIST_AGENTS]]'
    )
    result = strip_commands(text)
    assert "[[SOPHIA:" not in result
    assert "Some explanation" in result


def test_strip_empty_after_removal():
    text = '[[SOPHIA:LIST_AGENTS]]'
    result = strip_commands(text)
    assert result == ""


def test_strip_plain_text_unchanged():
    text = "Just normal text, nothing to strip."
    assert strip_commands(text) == text


def test_strip_preserves_content_around_command():
    text = "Before.\n[[SOPHIA:LIST_AGENTS]]\nAfter."
    result = strip_commands(text)
    assert "Before." in result
    assert "After." in result
    assert "[[SOPHIA:" not in result


def test_parse_prompt_with_bracket_in_value():
    # Prompt containing ] should not truncate the match
    text = '[[SOPHIA:RUN_AGENT name="Coder" prompt="fix bug in foo]bar.py"]]'
    cmds = parse_commands(text)
    assert len(cmds) == 1
    assert cmds[0]["args"]["name"] == "Coder"
    assert "foo]bar.py" in cmds[0]["args"]["prompt"]


def test_skip_permissions_no_string():
    # "no" should be treated as false (skip_perms=False)
    text = '[[SOPHIA:CREATE_AGENT name="A" role="coder" template="Coder" workspace="w" skip_permissions="no"]]'
    cmds = parse_commands(text)
    assert cmds[0]["args"]["skip_permissions"] == "no"
    # The actual falsy check is in execute_command, but we verify parsing captures it


def test_skip_permissions_zero_string():
    text = '[[SOPHIA:CREATE_AGENT name="A" role="coder" template="Coder" workspace="w" skip_permissions="0"]]'
    cmds = parse_commands(text)
    assert cmds[0]["args"]["skip_permissions"] == "0"
