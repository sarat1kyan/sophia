"""Unit tests for core/agent.py _build_extra_flags and orchestrator helpers."""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.agent import _build_extra_flags


# ── _build_extra_flags ────────────────────────────────────────────────────────

def test_skip_permissions_true():
    flags = _build_extra_flags({"skip_permissions": True})
    assert "--permission-mode" in flags
    assert "acceptEdits" in flags


def test_skip_permissions_false():
    flags = _build_extra_flags({"skip_permissions": False})
    assert "--permission-mode" not in flags


def test_effort_flag():
    flags = _build_extra_flags({"effort": "high"})
    assert "--effort" in flags
    assert "high" in flags


def test_model_flag():
    flags = _build_extra_flags({"model": "claude-opus-4"})
    assert "--model" in flags
    assert "claude-opus-4" in flags


def test_budget_flag():
    flags = _build_extra_flags({"max_budget_usd": 5.0})
    assert "--max-budget-usd" in flags
    idx = flags.index("--max-budget-usd")
    assert flags[idx + 1] == "5.0"


def test_allowed_tools_flag():
    flags = _build_extra_flags({"allowed_tools": "Bash,Write"})
    assert "--allowedTools" in flags
    assert "Bash,Write" in flags


def test_add_dirs_flag():
    flags = _build_extra_flags({"add_dirs": ["/opt/lib", "/opt/data"]})
    assert flags.count("--add-dir") == 2
    assert "/opt/lib" in flags
    assert "/opt/data" in flags


def test_resume_flag():
    flags = _build_extra_flags({}, resume_id="sess-abc")
    assert "--resume" in flags
    assert "sess-abc" in flags


def test_no_dangerously_skip_permissions():
    # This flag is blocked when running as root - must never appear
    flags = _build_extra_flags({"skip_permissions": True})
    assert "--dangerously-skip-permissions" not in flags


def test_empty_settings():
    flags = _build_extra_flags({})
    assert flags == []


def test_combined_flags():
    settings = {
        "skip_permissions": True,
        "effort": "max",
        "model": "claude-sonnet-4-6",
        "max_budget_usd": 2.0,
    }
    flags = _build_extra_flags(settings, resume_id="r-1")
    assert "--permission-mode" in flags
    assert "--effort" in flags
    assert "--model" in flags
    assert "--max-budget-usd" in flags
    assert "--resume" in flags
