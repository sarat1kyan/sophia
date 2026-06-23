from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


# ── Main menu ──────────────────────────────────────────────────────────────

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🤖 Agents",      callback_data="menu:agents"),
            InlineKeyboardButton(text="👥 Groups",      callback_data="menu:groups"),
        ],
        [
            InlineKeyboardButton(text="📁 Workspaces",  callback_data="menu:workspaces"),
            InlineKeyboardButton(text="🌐 SSH Hosts",   callback_data="menu:ssh"),
        ],
        [
            InlineKeyboardButton(text="💬 Sessions",    callback_data="menu:sessions"),
            InlineKeyboardButton(text="📋 Templates",   callback_data="menu:templates"),
        ],
        [
            InlineKeyboardButton(text="⏳ Pending",     callback_data="menu:pending"),
            InlineKeyboardButton(text="📊 Status",      callback_data="menu:status"),
        ],
        [
            InlineKeyboardButton(text="🎭 Sophia",      callback_data="menu_sophia"),
        ],
    ])


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:home")]
    ])


# ── Agents ─────────────────────────────────────────────────────────────────

def agents_list_keyboard(agents: list) -> InlineKeyboardMarkup:
    STATUS_ICON = {"idle": "💤", "running": "🟢", "done": "✅", "error": "🔴", "waiting_approval": "⏳"}
    buttons = []
    for a in agents:
        icon = STATUS_ICON.get(a["status"], "❓")
        buttons.append([InlineKeyboardButton(
            text=f"{icon} {a['name']}  [{a['role']}]",
            callback_data=f"agent_detail:{a['id']}",
        )])
    buttons.append([
        InlineKeyboardButton(text="➕ New Agent", callback_data="wizard:new_agent"),
        InlineKeyboardButton(text="🏠 Menu",      callback_data="menu:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def agent_detail_keyboard(agent_id: str, status: str) -> InlineKeyboardMarkup:
    running = status == "running"
    rows = []
    if running:
        rows.append([
            InlineKeyboardButton(text="⏹ Stop",  callback_data=f"agent_stop:{agent_id}"),
            InlineKeyboardButton(text="💀 Kill",  callback_data=f"agent_kill:{agent_id}"),
        ])
    else:
        rows.append([
            InlineKeyboardButton(text="▶ Start",    callback_data=f"agent_run:{agent_id}"),
            InlineKeyboardButton(text="↩ Resume",   callback_data=f"agent_resume:{agent_id}"),
        ])
        rows.append([
            InlineKeyboardButton(text="✏️ Rename",  callback_data=f"agent_rename:{agent_id}"),
            InlineKeyboardButton(text="📝 Sys Prompt", callback_data=f"agent_sysprompt:{agent_id}"),
        ])
    rows.append([
        InlineKeyboardButton(text="📨 Inject",   callback_data=f"agent_prompt:{agent_id}"),
        InlineKeyboardButton(text="⚙️ Settings", callback_data=f"agent_settings:{agent_id}"),
    ])
    rows.append([
        InlineKeyboardButton(text="📋 Clone",    callback_data=f"agent_clone:{agent_id}"),
        InlineKeyboardButton(text="🔄 Refresh",  callback_data=f"agent_detail:{agent_id}"),
    ])
    rows.append([
        InlineKeyboardButton(text="🗑 Delete",   callback_data=f"agent_delete_confirm:{agent_id}"),
        InlineKeyboardButton(text="‹ Agents",    callback_data="menu:agents"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def agent_delete_confirm_keyboard(agent_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Yes, delete", callback_data=f"agent_delete:{agent_id}"),
            InlineKeyboardButton(text="Cancel",       callback_data=f"agent_detail:{agent_id}"),
        ]
    ])


# ── Approvals ──────────────────────────────────────────────────────────────

def approval_keyboard(request_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve", callback_data=f"approve:{request_id}"),
            InlineKeyboardButton(text="❌ Deny",    callback_data=f"deny:{request_id}"),
        ]
    ])


# ── Templates ──────────────────────────────────────────────────────────────

def templates_list_keyboard(templates: list) -> InlineKeyboardMarkup:
    buttons = []
    for t in templates:
        icon = "⭐" if t["is_builtin"] else "✏️"
        buttons.append([InlineKeyboardButton(
            text=f"{icon} {t['name']}",
            callback_data=f"tpl_detail:{t['name']}",
        )])
    buttons.append([
        InlineKeyboardButton(text="➕ New Template", callback_data="wizard:new_template"),
        InlineKeyboardButton(text="🏠 Menu",         callback_data="menu:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def template_picker_keyboard(templates: list) -> InlineKeyboardMarkup:
    """Used in new_agent wizard for role selection."""
    buttons = []
    for t in templates:
        icon = "⭐" if t["is_builtin"] else "✏️"
        buttons.append([InlineKeyboardButton(
            text=f"{icon} {t['name']} - {(t['description'] or '')[:40]}",
            callback_data=f"tpl:{t['name']}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def template_detail_keyboard(name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Use This Template", callback_data=f"tpl_use:{name}")],
        [InlineKeyboardButton(text="‹ Back to Templates",  callback_data="menu:templates")],
    ])


# ── Workspaces ─────────────────────────────────────────────────────────────

def workspaces_list_keyboard(workspaces: list) -> InlineKeyboardMarkup:
    buttons = []
    for w in workspaces:
        icon = "🖥️" if w["runner_type"] == "local" else "🌐"
        buttons.append([InlineKeyboardButton(
            text=f"{icon} {w['name']}",
            callback_data=f"ws_detail:{w['id']}",
        )])
    buttons.append([
        InlineKeyboardButton(text="➕ New Workspace", callback_data="wizard:new_workspace"),
        InlineKeyboardButton(text="🏠 Menu",          callback_data="menu:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def workspace_detail_keyboard(ws_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Edit Path",        callback_data=f"ws_edit_path:{ws_id}")],
        [InlineKeyboardButton(text="🗑 Delete Workspace", callback_data=f"ws_delete_confirm:{ws_id}")],
        [InlineKeyboardButton(text="‹ Back to Workspaces", callback_data="menu:workspaces")],
    ])


def ws_delete_confirm_keyboard(ws_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Yes, delete", callback_data=f"ws_delete:{ws_id}"),
            InlineKeyboardButton(text="Cancel",       callback_data=f"ws_detail:{ws_id}"),
        ]
    ])


# ── SSH Hosts ──────────────────────────────────────────────────────────────

def ssh_list_keyboard(hosts: list) -> InlineKeyboardMarkup:
    buttons = []
    for h in hosts:
        buttons.append([InlineKeyboardButton(
            text=f"🖧 {h['alias']}  {h['username']}@{h['host']}:{h['port']}",
            callback_data=f"ssh_detail:{h['id']}",
        )])
    buttons.append([
        InlineKeyboardButton(text="➕ New SSH Host", callback_data="wizard:new_ssh"),
        InlineKeyboardButton(text="🏠 Menu",         callback_data="menu:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def ssh_detail_keyboard(host_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔌 Test Connection", callback_data=f"ssh_test:{host_id}"),
            InlineKeyboardButton(text="🗑 Delete",          callback_data=f"ssh_delete_confirm:{host_id}"),
        ],
        [InlineKeyboardButton(text="‹ Back to SSH Hosts", callback_data="menu:ssh")],
    ])


def ssh_delete_confirm_keyboard(host_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Yes, delete", callback_data=f"ssh_delete:{host_id}"),
            InlineKeyboardButton(text="Cancel",       callback_data=f"ssh_detail:{host_id}"),
        ]
    ])


# ── Sessions ───────────────────────────────────────────────────────────────

def sessions_list_keyboard(sessions: list) -> InlineKeyboardMarkup:
    buttons = []
    for s in sessions:
        label = s["agent_name"] or f"Session #{s['id']}"
        buttons.append([InlineKeyboardButton(
            text=f"💬 {label}  #{s['id']}",
            callback_data=f"session_detail:{s['id']}",
        )])
    buttons.append([InlineKeyboardButton(text="🏠 Menu", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def session_detail_keyboard(session_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📤 Export",  callback_data=f"session_export:{session_id}"),
            InlineKeyboardButton(text="🗑 Clear",   callback_data=f"session_clear_confirm:{session_id}"),
        ],
        [InlineKeyboardButton(text="‹ Back to Sessions", callback_data="menu:sessions")],
    ])


def session_clear_confirm_keyboard(session_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Yes, clear", callback_data=f"session_clear:{session_id}"),
            InlineKeyboardButton(text="Cancel",      callback_data=f"session_detail:{session_id}"),
        ]
    ])


# ── Groups ─────────────────────────────────────────────────────────────────

def groups_list_keyboard(groups: list) -> InlineKeyboardMarkup:
    buttons = []
    for g in groups:
        icon = "📡" if g["bridge_mode"] == "broadcast" else "👑"
        buttons.append([InlineKeyboardButton(
            text=f"{icon} {g['name']}",
            callback_data=f"group_detail:{g['id']}",
        )])
    buttons.append([
        InlineKeyboardButton(text="➕ New Group", callback_data="wizard:new_group"),
        InlineKeyboardButton(text="🏠 Menu",      callback_data="menu:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def group_detail_keyboard(group_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💣 Dissolve Group", callback_data=f"group_dissolve_confirm:{group_id}")],
        [InlineKeyboardButton(text="‹ Back to Groups",  callback_data="menu:groups")],
    ])


def group_dissolve_confirm_keyboard(group_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Yes, dissolve", callback_data=f"group_dissolve:{group_id}"),
            InlineKeyboardButton(text="Cancel",         callback_data=f"group_detail:{group_id}"),
        ]
    ])


# ── FSM helpers ────────────────────────────────────────────────────────────

def runner_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💻 Local",  callback_data="runner:local"),
            InlineKeyboardButton(text="🌐 SSH",    callback_data="runner:ssh"),
        ],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel")],
    ])


def bridge_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📡 Broadcast",  callback_data="bridge:broadcast"),
            InlineKeyboardButton(text="👑 Supervisor",  callback_data="bridge:supervisor"),
        ],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel")],
    ])


def auth_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔑 SSH Key",   callback_data="ssh_auth:key"),
            InlineKeyboardButton(text="🔐 Password",  callback_data="ssh_auth:password"),
        ],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel")],
    ])


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel")]
    ])


def yes_no_keyboard(yes_cb: str, no_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Yes", callback_data=yes_cb),
            InlineKeyboardButton(text="❌ No",  callback_data=no_cb),
        ]
    ])


# ── Agent Settings ──────────────────────────────────────────────────────────

def agent_settings_keyboard(agent_id: str, settings: dict) -> InlineKeyboardMarkup:
    skip = "✅ ON" if settings.get("skip_permissions") else "❌ OFF"
    effort = settings.get("effort") or "default"
    model = settings.get("model") or "default"
    budget = f"${settings['max_budget_usd']}" if settings.get("max_budget_usd") else "none"
    timeout = f"{settings['timeout_seconds']}s" if settings.get("timeout_seconds") else "none"
    stream_icon = {"full": "🔊", "tools": "🔧", "silent": "🔇"}
    stream_mode = settings.get("stream_mode", "full")
    stream_label = f"{stream_icon.get(stream_mode, '🔊')} Output: {stream_mode}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔓 Skip Permissions: {skip}", callback_data=f"agt_set_toggle_skip:{agent_id}")],
        [InlineKeyboardButton(text=stream_label,                   callback_data=f"agt_set_stream:{agent_id}")],
        [InlineKeyboardButton(text=f"⚡ Effort: {effort}",         callback_data=f"agt_set_effort:{agent_id}")],
        [InlineKeyboardButton(text=f"🤖 Model: {model}",           callback_data=f"agt_set_model:{agent_id}")],
        [InlineKeyboardButton(text=f"💰 Budget: {budget}",         callback_data=f"agt_set_budget:{agent_id}")],
        [InlineKeyboardButton(text=f"⏱ Timeout: {timeout}",       callback_data=f"agt_set_timeout:{agent_id}")],
        [InlineKeyboardButton(text=f"🛠 Allowed Tools",            callback_data=f"agt_set_tools:{agent_id}")],
        [InlineKeyboardButton(text="‹ Back to Agent",              callback_data=f"agent_detail:{agent_id}")],
    ])


def kill_during_run_keyboard(agent_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💀 Kill agent", callback_data=f"agent_kill:{agent_id}")]
    ])


def effort_keyboard(agent_id: str) -> InlineKeyboardMarkup:
    levels = [("low", "🐢"), ("medium", "🚗"), ("high", "🚀"), ("xhigh", "⚡"), ("max", "🔥")]
    rows = []
    row = []
    for level, icon in levels:
        row.append(InlineKeyboardButton(text=f"{icon} {level}", callback_data=f"agt_effort:{agent_id}:{level}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton(text="default", callback_data=f"agt_effort:{agent_id}:default"),
        InlineKeyboardButton(text="❌ Cancel", callback_data=f"agent_settings:{agent_id}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
