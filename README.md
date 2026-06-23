<div align="center">

<h1>SOPHIA</h1>

<p><strong>Run Claude Code agents from Telegram - spawn, stream, orchestrate.</strong></p>

<p>
  <img src="https://img.shields.io/badge/build-passing-22c55e?style=flat-square" alt="Build" />
  <img src="https://img.shields.io/badge/python-3.11%2B-3b82f6?style=flat-square&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/aiogram-3.x-8b5cf6?style=flat-square" alt="aiogram" />
  <img src="https://img.shields.io/badge/Claude_Code-CLI-f97316?style=flat-square" alt="Claude Code" />
  <img src="https://img.shields.io/badge/SQLite-aiosqlite-06b6d4?style=flat-square&logo=sqlite&logoColor=white" alt="SQLite" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-64748b?style=flat-square" alt="License" /></a>
</p>

</div>

---

SOPHIA is a self-hosted Telegram bot that wraps the Claude Code CLI into a full agent orchestration platform. You create agents, assign them to project directories, send them tasks, and watch the output stream directly into your Telegram chat - with live tool notifications, a Kill button on every action, SSH remote execution, and Sophia: a meta-agent that reads your request and automatically creates workspaces, spawns the right specialists, and starts them all.

---

## What it looks like

```
You                    SOPHIA                     Claude Code (subprocess)
─────────────────────────────────────────────────────────────────────────

/sophia
"Build a REST API with tests"
───────────────────────────►

                           🎭 [Sophia]
                           [[SOPHIA:CREATE_WORKSPACE name="api" path="/workspaces/api"]]
                           ✅ Workspace api created at /workspaces/api

                           🎭 [Sophia]
                           [[SOPHIA:CREATE_AGENT name="Coder" template="Coder" workspace="api"]]
                           ✅ Agent Coder [coder] created

                           🎭 [Sophia]
                           [[SOPHIA:RUN_AGENT name="Coder" prompt="Implement a FastAPI..."]]
                           🚀 Agent Coder started

                                                    spawn subprocess
                                                   ─────────────────►

◄──── ⚡ [Coder] → Bash ─────────────────────────────────────────────
      pip install fastapi uvicorn
      [💀 Kill agent]

◄──── 🔧 [Coder] → Write ────────────────────────────────────────────
      /workspaces/api/main.py
      [💀 Kill agent]

◄──── 🤖 [Coder] ────────────────────────────────────────────────────
      Created FastAPI app with 4 endpoints:
      POST /users · GET /users/{id}
      PUT /users/{id} · DELETE /users/{id}
      Running tests now...

◄──── ✅ [Coder] done. ──────────────────────────────────────────────
```

Every tool call arrives as a **separate message** the moment Claude makes it. You see exactly what the agent is doing and can kill it at any point.

---

## Features

### 🎭 Sophia - Meta-Orchestrator

The standout feature. Sophia is a special agent that understands natural language requests and automatically sets up your entire project:

- Creates a workspace directory on disk
- Spawns the right specialist agents (Coder, Tester, Reviewer, DevOps...)
- Sends each agent a detailed, specific task prompt
- Gets them all running - without you touching a menu

Just tell Sophia what you want to build and watch the agents go to work.

```
/sophia → "Build a price tracker that monitors Amazon and eBay,
           stores results in SQLite, and sends Telegram alerts"
```

Sophia creates `price_tracker` workspace, spawns Coder + Tester, and kicks them off - all automatically.

---

### 🤖 Agents

- Create from built-in templates: **Coder · Tester · Reviewer · DevOps · Monitor**
- Or create fully custom agents with any system prompt
- Clone, rename, edit system prompt on the fly
- Resume any previous Claude conversation with `--resume`
- Run count + last-run timestamp per agent
- `/run <name> <task>` - no menus, one command

### ⚡ Live Tool Streaming

Every tool call Claude makes arrives as a dedicated Telegram message **before** the tool executes:

| Icon | Tool type | Examples |
|------|-----------|---------|
| ⚡ | Sensitive (shell) | Bash, exec |
| 🔧 | File operations | Write, Edit, Read, MultiEdit |

The agent's text output streams in real-time as Claude thinks and writes. Long outputs split automatically at 4096 chars (Telegram's limit).

### ⚙️ Per-Agent Settings

Every agent can be configured independently via the ⚙️ button:

| Setting | Effect |
|---------|--------|
| Skip permissions | `--permission-mode acceptEdits` - agents read/write files without asking |
| Effort | `--effort low/medium/high/xhigh/max` |
| Model | `--model <any Claude model ID>` |
| Budget cap | `--max-budget-usd N` - hard spending limit per run |
| Timeout | Auto-kill after N seconds via `asyncio.wait_for` |
| Allowed tools | `--allowedTools Read,Write` - block shell access entirely |
| Extra env vars | Injected into the subprocess environment |

### 🔗 Multi-Agent Groups

Put agents in a group and they share a broadcast context bus:

- **Broadcast mode** - every agent sees every other agent's output in real time
- **Supervisor mode** - one agent directs the others by injecting prompts

Example: Coder writes code, Monitor receives every line, runs the test suite, and injects failure reports back into the group channel.

### 💬 Session Management

- Full message history per agent session (user + assistant turns)
- Export any session as a `.txt` file sent to Telegram
- Store Claude's session UUID → tap **Resume** to continue with full context
- Clear sessions to free DB space

### 🌐 SSH Remote Execution

Run agents on remote machines over SSH:

- Key or password authentication
- `/test_ssh` - verify the connection before you run anything
- Creates a workspace on the remote path
- Streams output back to Telegram identically to local

### 🔐 Access Control

- Per-user allowlist in `config.yaml`
- Admin-only commands (`/logs`, `/restart`, `/stop_all`, `/kill_all`, `/add_user`)
- Add/remove users at runtime without restart

---

## How it works - internals

```
Telegram message
    │
    ▼
aiogram 3 dispatcher  ──►  AuthMiddleware (allowlist check)
    │
    ▼
Handler (FSM wizard or direct command)
    │
    ▼
orchestrator.start_agent()
    │  creates AgentStreamer(bot, chat_id, agent_name)
    │  launches asyncio.Task → agent._run()
    │
    ▼
agent._run()
    │  builds CLI flags from agent.settings
    │  LocalRunner.start()  → asyncio.create_subprocess_exec
    │     claude --permission-mode acceptEdits -p
    │            --output-format stream-json --verbose
    │            <prompt>
    │
    ▼
LocalRunner.stream()  ─── reads stdout line by line
    │
    │  _extract_text(raw)  ──►  assistant.content blocks
    │                            tool_use blocks  → {name, summary}
    │                            system.init      → session_id
    │
    ▼  (per line)
agent._run() loop
    │
    ├── tool_use?  ──►  streamer.send_tool_notice()   → separate ⚡/🔧 message + Kill button
    │                   reset _current_msg_id          → next text starts new message below
    │
    ├── orchestrator role + [[SOPHIA:CMD]]?
    │       ──►  meta_commands.parse_commands()
    │            meta_commands.execute_command()       → create workspace/agent/run
    │            streamer.send_orchestrator_notice()   → 🎭 feedback bubble
    │
    └── text line  ──►  streamer.feed(line)
                            buffer → edit_message_text (in-place update)
                            overflow 4096 chars → new message
    │
    ▼
process exit
    ├── save_message(session, assistant, full_output)
    └── streamer.send_final("done" | "timeout" | "error")
```

---

## Quick start

### One-command install (Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/sarat1kyan/sophia/main/install.sh | sudo bash
```

Creates a dedicated `sophia` system user, installs Claude Code CLI, sets up the Python venv, and registers a systemd service.

Then configure:

```bash
sudo -u sophia bash -c 'cd /opt/sophia && .venv/bin/python3 SOPHIA.py --setup'
systemctl start SOPHIA
```

### Manual install

```bash
git clone https://github.com/sarat1kyan/sophia.git
cd sophia
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 SOPHIA.py --setup   # interactive wizard
python3 SOPHIA.py
```

### Setup wizard prompts

| Prompt | Where to get it |
|--------|----------------|
| Bot token | [@BotFather](https://t.me/BotFather) → `/newbot` |
| Your Telegram user ID | [@userinfobot](https://t.me/userinfobot) |
| Approved user IDs | Comma-separated list (include your own) |

---

## Configuration

`config/config.yaml` (created by the setup wizard, never committed):

```yaml
telegram:
  bot_token: "YOUR_TOKEN"
  admin_id: 123456789
  approved_users:
    - 123456789

sophia:
  log_level: INFO
  log_file: logs/SOPHIA.log
  db_path: storage/SOPHIA.db
  stream_chunk_lines: 1          # 1 = every line sent instantly
  approval_timeout_seconds: 300  # auto-deny after this many seconds

claude:
  cli_path: claude               # or absolute path
  default_flags:
    - "--permission-mode"
    - "acceptEdits"              # applied to every agent by default
```

---

## Role templates

Built-in templates define a specialist's system prompt. Choose one when creating an agent, or write your own.

| Template | What it does |
|----------|-------------|
| **Sophia** | Meta-orchestrator - reads your goal and spawns the right agents automatically |
| **Coder** | Implements features, writes clean production code, commits with clear messages |
| **Tester** | Writes unit/integration/e2e tests, reports coverage and failures |
| **Reviewer** | Code review with CRITICAL/HIGH/MEDIUM/LOW severity ratings and fix suggestions |
| **DevOps** | Docker, CI/CD pipelines, infrastructure automation, deployment scripts |
| **Monitor** | Watches other agents' output, runs tests automatically, injects findings |

Create custom templates with `/new_template` or via the Templates menu.

---

## Command reference

<details>
<summary><strong>Dashboard & admin</strong></summary>

| Command | Description |
|---------|-------------|
| `/start` | Home dashboard - agent counts, pending approvals, menu |
| `/help` | Full command reference |
| `/status` | Live view: all agents, groups, pending approvals with run stats |
| `/ping` | Health check - uptime and counts |
| `/logs` | Tail last 50 lines of SOPHIA.log in-chat |
| `/config` | Show active config (token redacted) |
| `/restart` | Restart systemd service (admin only) |
| `/stop_all` | Gracefully stop every running agent |
| `/kill_all` | Force-kill every running agent |
| `/add_user <id>` | Add approved user at runtime |
| `/remove_user <id>` | Remove user |
| `/users` | List approved users |

</details>

<details>
<summary><strong>Sophia</strong></summary>

| Command | Description |
|---------|-------------|
| `/sophia` | Talk to Sophia - describe what you want to build and she handles the rest |

Sophia understands these commands in her output:

```
[[SOPHIA:CREATE_WORKSPACE name="proj" path="/workspaces/proj"]]
[[SOPHIA:CREATE_AGENT name="Coder" role="coder" template="Coder" workspace="proj"]]
[[SOPHIA:RUN_AGENT name="Coder" prompt="Implement the feature..."]]
[[SOPHIA:LIST_AGENTS]]
[[SOPHIA:LIST_WORKSPACES]]
```

</details>

<details>
<summary><strong>Agents</strong></summary>

| Command | Description |
|---------|-------------|
| `/new_agent` | Wizard: name → template → workspace → immediate task |
| `/agents` | List all agents with status, workspace, run count |
| `/run <name> <task>` | Quick-start: no menus, fires immediately |
| `/start_agent <id> <prompt>` | Start with explicit ID |
| `/stop_agent <id>` | Graceful stop (SIGTERM + 5s wait) |
| `/kill_agent <id>` | Immediate SIGKILL |
| `/rename_agent <id> <name>` | Rename in place |
| `/delete_agent <id>` | Delete agent + all session history |
| `/prompt <id> <text>` | Inject text into a running agent's stdin |

**Buttons on every agent detail card:**
```
[ ▶ Start ]  [ ↩ Resume ]  [ 📨 Inject ]
[ ✏️ Rename ] [ 📝 Sys Prompt ] [ ⚙️ Settings ]
[ 📋 Clone ]  [ 🔄 Refresh ]   [ 🗑 Delete ]
```

</details>

<details>
<summary><strong>Sessions</strong></summary>

| Command | Description |
|---------|-------------|
| `/sessions` | List all sessions with agent names and timestamps |
| `/session <id>` | View messages in a session |
| `/export_session <id>` | Send session as a `.txt` file |
| `/clear_session <id>` | Delete all messages in a session |

</details>

<details>
<summary><strong>Workspaces</strong></summary>

| Command | Description |
|---------|-------------|
| `/workspaces` | List workspaces - path, runner type, status |
| `/new_workspace` | Wizard: name → path → local or SSH |
| `/delete_workspace <id>` | Remove workspace |

</details>

<details>
<summary><strong>SSH hosts</strong></summary>

| Command | Description |
|---------|-------------|
| `/ssh_hosts` | List configured hosts |
| `/new_ssh_host` | Add host - alias, IP, port, user, key or password |
| `/test_ssh <id>` | Test connection, returns error message if it fails |
| `/delete_ssh_host <id>` | Remove host |

</details>

<details>
<summary><strong>Groups (multi-agent)</strong></summary>

| Command | Description |
|---------|-------------|
| `/new_group` | Create group - name + bridge mode |
| `/groups` | List groups |
| `/add_to_group <gid> <aid>` | Add agent to group |
| `/remove_from_group <gid> <aid>` | Remove agent from group |
| `/dissolve_group <id>` | Delete group (agents remain) |

</details>

<details>
<summary><strong>Templates</strong></summary>

| Command | Description |
|---------|-------------|
| `/templates` | List all templates (built-in + custom) |
| `/template <name>` | View system prompt for a template |
| `/new_template` | Create custom template |

</details>

---

## Multi-agent example

```bash
# 1. Create workspace
/new_workspace  →  myproject  /home/user/myproject  Local

# 2. Create agents
/new_agent  →  Alice  [Coder]    myproject
/new_agent  →  Bob   [Monitor]   myproject

# 3. Link them in a group
/new_group  →  dev-team  Broadcast
/add_to_group 1 <alice-id>
/add_to_group 1 <bob-id>

# 4. Fire
/run alice "Implement JWT auth with refresh tokens and full test coverage"
```

Alice writes code and commits. Bob sees every line via the broadcast bus, automatically runs the test suite on each commit, and injects failure reports directly back into the group - which Alice reads and acts on.

---

## SSH remote example

```bash
# 1. Register the server
/new_ssh_host
  Alias: prod · Host: 10.0.0.5 · Port: 22
  User: ubuntu · Auth: Key · /root/.ssh/id_rsa

# 2. Verify
/test_ssh 1   →   ✅ Connection successful (latency 12ms)

# 3. Remote workspace
/new_workspace  →  prod-api  /opt/api  SSH  host: prod

# 4. Run on the remote
/new_agent  →  DeployBot  [DevOps]  prod-api
/run deploybot "Update nginx config, reload service, run smoke tests"
```

Claude Code runs on the remote machine. Output streams back to Telegram identically to local - tool calls, text, and the final ✅.

---

## Architecture

```
sophia/
├── SOPHIA.py                     entry point · setup wizard · SIGTERM handler
│
├── core/
│   ├── orchestrator.py           agent registry (_agents) · lifecycle · bulk ops
│   ├── agent.py                  settings → CLI flags → subprocess · timeout · orchestrator interception
│   ├── meta_commands.py          Sophia command parser + executor
│   ├── bridge.py                 async pub/sub bus for agent groups
│   ├── session.py                session CRUD · claude_session_id storage
│   ├── workspace.py              workspace + SSH host CRUD
│   └── approval.py               asyncio.Future gate per approval request
│
├── transport/
│   ├── local_runner.py           asyncio subprocess · stream-json parser · tool-use metadata
│   └── ssh_runner.py             asyncssh remote runner (identical interface)
│
├── streaming/
│   └── streamer.py               line buffer → in-place Telegram edits
│                                 send_tool_notice · send_orchestrator_notice · send_final
│
├── bot/
│   ├── bot.py                    Dispatcher · AuthMiddleware · command list
│   ├── auth.py                   per-request allowlist enforcement
│   ├── keyboards.py              all InlineKeyboardMarkup builders
│   └── handlers/
│       ├── agents.py             agent CRUD · settings · clone · resume · /run
│       ├── sophia.py             /sophia shortcut · auto-create Sophia agent
│       ├── admin.py              /ping · /logs · /stop_all · /kill_all · /restart
│       ├── workspace.py          workspace wizard + path editing
│       ├── ssh.py                SSH host wizard + connection test
│       ├── sessions.py           session list · export · clear
│       ├── approvals.py          pending list · approve/deny callbacks
│       ├── groups.py             group wizard · membership
│       └── templates.py          template list · create custom
│
├── storage/
│   ├── db.py                     aiosqlite connection · FK enforcement · auto-migrations
│   └── models.py                 schema DDL for 9 tables
│
└── templates/
    ├── sophia.yaml               meta-orchestrator prompt with [[SOPHIA:CMD]] docs
    ├── coder.yaml
    ├── tester.yaml
    ├── reviewer.yaml
    ├── devops.yaml
    └── monitor.yaml
```

---

## Database

Nine tables, FK enforcement on, cascading deletes. Schema migrations run on every startup - no manual steps when upgrading.

| Table | Key columns |
|-------|-------------|
| `agents` | `id` (UUID) · `role` · `status` · `run_count` · `settings` (JSON) |
| `sessions` | `agent_id` (FK cascade) · `claude_session_id` |
| `messages` | `session_id` (FK cascade) · `role` · `content` |
| `workspaces` | `name` · `path` · `runner_type` · `ssh_host_id` |
| `ssh_hosts` | `host` · `port` · `username` · `key_path` · `password` |
| `agent_groups` | `bridge_mode` (`broadcast` / `supervisor`) |
| `approval_requests` | `status` (`pending` / `approved` / `denied`) |
| `templates` | `system_prompt` · `is_builtin` |
| `users` | `telegram_id` · `role` |

---

## Requirements

| Requirement | Version |
|-------------|---------|
| Python | 3.11+ |
| Node.js | 20+ (for Claude Code CLI) |
| Claude Code CLI | `npm install -g @anthropic-ai/claude-code` |
| Telegram bot token | From [@BotFather](https://t.me/BotFather) |

---

## Troubleshooting

<details>
<summary><strong>Bot not responding</strong></summary>

```bash
journalctl -u SOPHIA -f
# or
tail -f /opt/sophia/logs/SOPHIA.log
```

Confirm your Telegram ID is in `approved_users` in `config.yaml`. Send `/start` - if the bot is alive it responds immediately.

</details>

<details>
<summary><strong>claude: command not found</strong></summary>

```bash
npm install -g @anthropic-ai/claude-code
which claude
claude --version
```

If running as a service user, set `cli_path` in config to the full absolute path (e.g. `/root/.local/bin/claude`).

</details>

<details>
<summary><strong>Agents fail instantly with permission error</strong></summary>

SOPHIA uses `--permission-mode acceptEdits` by default, which works as any user including root. The old `--dangerously-skip-permissions` flag is blocked when running as root - do not use it in `default_flags`.

</details>

<details>
<summary><strong>Workspace path does not exist</strong></summary>

The agent card shows `⚠️ Path does not exist`. Either create the directory:

```bash
mkdir -p /your/project/path
```

Or edit the workspace path from the Workspaces menu.

</details>

<details>
<summary><strong>Agent running forever</strong></summary>

Set **Timeout** in ⚙️ Settings - SOPHIA kills the subprocess after that many seconds and sends `⏱ [name] timed out.`

Or stop immediately: `/kill_agent <id>` or `/kill_all`.

</details>

<details>
<summary><strong>SSH connection failing</strong></summary>

Run `/test_ssh <id>` - the error is shown in-chat. Common causes:

- Key permissions: `chmod 600 ~/.ssh/id_rsa`
- `claude` not installed on the remote host
- Firewall blocking port 22

</details>

---

## Service management

**Linux (systemd)**
```bash
systemctl start   SOPHIA
systemctl stop    SOPHIA
systemctl restart SOPHIA
systemctl status  SOPHIA
journalctl -u SOPHIA -f
```

**macOS (launchd)**
```bash
launchctl start io.sophia
launchctl stop  io.sophia
tail -f /opt/sophia/logs/SOPHIA.log
```

---

<div align="center">
<sub>Built with <a href="https://github.com/aiogram/aiogram">aiogram 3</a> · <a href="https://docs.anthropic.com/claude-code">Claude Code CLI</a> · <a href="https://github.com/omnilib/aiosqlite">aiosqlite</a></sub>
</div>
