#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/sarat1kyan/sophia.git"
INSTALL_DIR="${SOPHIA_DIR:-/opt/sophia}"
SERVICE_NAME="SOPHIA"
SERVICE_USER="sophia"
PYTHON_MIN="3.11"
NODE_MIN="20"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── pre-flight ────────────────────────────────────────────────────────────────

check_root() {
    if [[ $EUID -ne 0 ]]; then
        error "This installer must be run as root. Try: sudo bash install.sh"
    fi
}

detect_os() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        OS="macos"; PKG="brew"
    elif command -v apt-get &>/dev/null; then
        OS="debian"; PKG="apt"
    elif command -v dnf &>/dev/null; then
        OS="fedora"; PKG="dnf"
    elif command -v yum &>/dev/null; then
        OS="rhel"; PKG="yum"
    elif command -v pacman &>/dev/null; then
        OS="arch"; PKG="pacman"
    else
        error "Unsupported OS. Please install dependencies manually."
    fi
    info "Detected OS: $OS (package manager: $PKG)"
}

# ── user creation ─────────────────────────────────────────────────────────────

create_service_user() {
    if id "$SERVICE_USER" &>/dev/null; then
        info "User '$SERVICE_USER' already exists - skipping creation"
    else
        info "Creating dedicated user '$SERVICE_USER'..."
        if [[ "$OS" == "macos" ]]; then
            # Find the next available UID above 500
            NEXT_UID=$(dscl . -list /Users UniqueID | awk '{print $2}' | sort -n | tail -1)
            NEXT_UID=$((NEXT_UID + 1))
            dscl . -create /Users/$SERVICE_USER
            dscl . -create /Users/$SERVICE_USER UserShell /bin/bash
            dscl . -create /Users/$SERVICE_USER RealName "SOPHIA Bot"
            dscl . -create /Users/$SERVICE_USER UniqueID "$NEXT_UID"
            dscl . -create /Users/$SERVICE_USER PrimaryGroupID 20
            dscl . -create /Users/$SERVICE_USER NFSHomeDirectory "/Users/$SERVICE_USER"
            mkdir -p "/Users/$SERVICE_USER"
            chown "$SERVICE_USER":staff "/Users/$SERVICE_USER"
        else
            useradd \
                --create-home \
                --shell /bin/bash \
                --comment "SOPHIA Claude Code Agent Orchestrator" \
                "$SERVICE_USER"
        fi
        success "User '$SERVICE_USER' created"
    fi

    # Grant passwordless sudo so agents can run privileged commands
    SUDOERS_FILE="/etc/sudoers.d/$SERVICE_USER"
    if [[ ! -f "$SUDOERS_FILE" ]]; then
        info "Granting sudo access to '$SERVICE_USER'..."
        echo "$SERVICE_USER ALL=(ALL) NOPASSWD: ALL" > "$SUDOERS_FILE"
        chmod 440 "$SUDOERS_FILE"
        # Validate the sudoers entry
        visudo -cf "$SUDOERS_FILE" || { rm -f "$SUDOERS_FILE"; error "Invalid sudoers entry - aborted"; }
        success "Sudo access granted to '$SERVICE_USER'"
    else
        info "Sudoers entry for '$SERVICE_USER' already exists"
    fi
}

# ── system dependencies ───────────────────────────────────────────────────────

install_system_deps() {
    info "Installing system dependencies..."
    case "$PKG" in
        apt)
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq
            apt-get install -y -qq curl git wget python3 python3-pip python3-venv build-essential sudo
            ;;
        dnf)
            dnf install -y curl git wget python3 python3-pip gcc make sudo
            ;;
        yum)
            yum install -y curl git wget python3 python3-pip gcc make sudo
            ;;
        pacman)
            pacman -Sy --noconfirm curl git wget python python-pip base-devel sudo
            ;;
        brew)
            brew install curl git wget python3 || true
            ;;
    esac
    success "System dependencies installed"
}

check_python_version() {
    if ! command -v python3 &>/dev/null; then
        error "python3 not found after installation"
    fi
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
    REQ_MINOR=$(echo "$PYTHON_MIN" | cut -d. -f2)
    if [[ $PY_MAJOR -lt 3 ]] || [[ $PY_MAJOR -eq 3 && $PY_MINOR -lt $REQ_MINOR ]]; then
        error "Python $PYTHON_MIN+ required, found $PY_VER"
    fi
    success "Python $PY_VER"
}

install_nodejs() {
    if command -v node &>/dev/null; then
        NODE_VER=$(node --version | tr -d 'v' | cut -d. -f1)
        if [[ $NODE_VER -ge $NODE_MIN ]]; then
            success "Node.js $(node --version) already installed"
            return
        fi
        warn "Node.js version too old ($NODE_VER < $NODE_MIN), upgrading..."
    fi

    info "Installing Node.js $NODE_MIN+..."
    case "$PKG" in
        apt)
            curl -fsSL https://deb.nodesource.com/setup_${NODE_MIN}.x | bash -
            apt-get install -y -qq nodejs
            ;;
        dnf|yum)
            curl -fsSL https://rpm.nodesource.com/setup_${NODE_MIN}.x | bash -
            ${PKG} install -y nodejs
            ;;
        pacman)
            pacman -S --noconfirm nodejs npm
            ;;
        brew)
            brew install node@${NODE_MIN} || brew install node
            ;;
    esac
    success "Node.js $(node --version) installed"
}

install_claude_code() {
    if command -v claude &>/dev/null; then
        success "Claude Code CLI already installed: $(claude --version 2>/dev/null || echo 'unknown version')"
    else
        info "Installing Claude Code CLI globally..."
        npm install -g @anthropic-ai/claude-code
        success "Claude Code CLI installed at $(command -v claude)"
    fi

    # If claude is installed under a root-only path (e.g. ~/.local/bin), ensure the
    # service user can execute it by making the parent directories world-traversable.
    CLAUDE_REAL=$(readlink -f "$(command -v claude)" 2>/dev/null || true)
    if [[ -n "$CLAUDE_REAL" && "$CLAUDE_REAL" == /root/* ]]; then
        info "Fixing claude binary permissions for non-root access..."
        chmod o+x /root /root/.local /root/.local/share /root/.local/bin 2>/dev/null || true
        success "Claude binary at $CLAUDE_REAL is now accessible to $SERVICE_USER"
    fi
}

# ── repository ────────────────────────────────────────────────────────────────

clone_or_update_repo() {
    if [[ -d "$INSTALL_DIR/.git" ]]; then
        info "Repository already exists at $INSTALL_DIR, pulling latest..."
        git -C "$INSTALL_DIR" pull --ff-only || warn "Could not pull latest (local changes?)"
    elif [[ -d "$INSTALL_DIR" && -f "$INSTALL_DIR/SOPHIA.py" ]]; then
        info "SOPHIA already present at $INSTALL_DIR (non-git), skipping clone"
    else
        info "Cloning SOPHIA to $INSTALL_DIR..."
        git clone "$REPO_URL" "$INSTALL_DIR"
    fi

    # Ensure the sophia user owns the entire install directory
    chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"
    # Logs and storage must be writable
    mkdir -p "$INSTALL_DIR/logs" "$INSTALL_DIR/storage" "$INSTALL_DIR/config"
    chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR/logs" "$INSTALL_DIR/storage" "$INSTALL_DIR/config"
    success "Repository ready at $INSTALL_DIR (owned by $SERVICE_USER)"
}

# ── Python venv ───────────────────────────────────────────────────────────────

setup_virtualenv() {
    info "Setting up Python virtual environment as '$SERVICE_USER'..."
    sudo -u "$SERVICE_USER" bash -c "
        cd '$INSTALL_DIR'
        if [[ ! -d .venv ]]; then
            python3 -m venv .venv
        fi
        .venv/bin/pip install --quiet --upgrade pip
        .venv/bin/pip install --quiet -r requirements.txt
    "
    success "Virtual environment ready"
}

# ── setup wizard ──────────────────────────────────────────────────────────────

run_setup_wizard() {
    if [[ -f "$INSTALL_DIR/config/config.yaml" ]]; then
        info "config/config.yaml already exists - skipping setup wizard"
        return
    fi
    info "Running first-time setup wizard as '$SERVICE_USER'..."
    sudo -u "$SERVICE_USER" bash -c "
        cd '$INSTALL_DIR'
        .venv/bin/python3 SOPHIA.py --setup
    "
}

# ── service installation ──────────────────────────────────────────────────────

install_systemd_service() {
    if [[ "$OS" == "macos" ]]; then
        install_launchd_service
        return
    fi
    if ! command -v systemctl &>/dev/null; then
        warn "systemd not found - skip service installation"
        return
    fi

    SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
    info "Installing systemd service to $SERVICE_FILE (running as '$SERVICE_USER')..."

    USER_HOME=$(getent passwd "$SERVICE_USER" | cut -d: -f6)

    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=SOPHIA Claude Code Agent Orchestrator
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/.venv/bin/python3 ${INSTALL_DIR}/SOPHIA.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1
Environment=HOME=${USER_HOME}
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}" || true
    success "systemd service installed and enabled (User=${SERVICE_USER})"
}

install_launchd_service() {
    USER_HOME=$(dscl . -read /Users/$SERVICE_USER NFSHomeDirectory 2>/dev/null | awk '{print $2}' || echo "/Users/$SERVICE_USER")
    PLIST_DIR="/Library/LaunchDaemons"
    PLIST_PATH="$PLIST_DIR/io.sophia.plist"
    info "Installing launchd daemon to $PLIST_PATH (as '$SERVICE_USER')..."

    cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>             <string>io.sophia</string>
    <key>UserName</key>          <string>${SERVICE_USER}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${INSTALL_DIR}/.venv/bin/python3</string>
        <string>${INSTALL_DIR}/SOPHIA.py</string>
    </array>
    <key>WorkingDirectory</key>  <string>${INSTALL_DIR}</string>
    <key>RunAtLoad</key>         <true/>
    <key>KeepAlive</key>         <true/>
    <key>StandardOutPath</key>   <string>${INSTALL_DIR}/logs/SOPHIA.log</string>
    <key>StandardErrorPath</key> <string>${INSTALL_DIR}/logs/SOPHIA.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>          <string>${USER_HOME}</string>
        <key>PATH</key>          <string>/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin</string>
    </dict>
</dict>
</plist>
EOF

    chown root:wheel "$PLIST_PATH"
    chmod 644 "$PLIST_PATH"
    launchctl load "$PLIST_PATH" 2>/dev/null || true
    success "launchd daemon installed (User=${SERVICE_USER})"
}

# ── banner ────────────────────────────────────────────────────────────────────

print_banner() {
    echo ""
    echo -e "${BOLD}${GREEN}"
    echo "  ████████╗███████╗██████╗ ███╗   ███╗███████╗███████╗"
    echo "     ██╔══╝██╔════╝██╔══██╗████╗ ████║██╔════╝██╔════╝"
    echo "     ██║   █████╗  ██████╔╝██╔████╔██║█████╗  ███████╗"
    echo "     ██║   ██╔══╝  ██╔══██╗██║╚██╔╝██║██╔══╝  ╚════██║"
    echo "     ██║   ███████╗██║  ██║██║ ╚═╝ ██║███████╗███████║"
    echo "     ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚══════╝╚══════╝"
    echo -e "${NC}"
    echo -e "${CYAN}  Claude Code Agent Orchestrator for Telegram${NC}"
    echo ""
    echo -e "${GREEN}Installation complete!${NC}"
    echo ""
    echo -e "  ${BOLD}Service user:${NC}  ${CYAN}${SERVICE_USER}${NC} (sudoers: /etc/sudoers.d/${SERVICE_USER})"
    echo -e "  ${BOLD}Install dir:${NC}   ${CYAN}${INSTALL_DIR}${NC}"
    echo ""
    if [[ "$OS" == "macos" ]]; then
        echo -e "  ${BOLD}Start:${NC}   ${CYAN}launchctl start io.sophia${NC}"
        echo -e "  ${BOLD}Stop:${NC}    ${CYAN}launchctl stop io.sophia${NC}"
        echo -e "  ${BOLD}Logs:${NC}    ${CYAN}tail -f ${INSTALL_DIR}/logs/SOPHIA.log${NC}"
    else
        echo -e "  ${BOLD}Start:${NC}   ${CYAN}systemctl start ${SERVICE_NAME}${NC}"
        echo -e "  ${BOLD}Status:${NC}  ${CYAN}systemctl status ${SERVICE_NAME}${NC}"
        echo -e "  ${BOLD}Logs:${NC}    ${CYAN}journalctl -u ${SERVICE_NAME} -f${NC}"
    fi
    echo -e "  ${BOLD}Manual:${NC}  ${CYAN}sudo -u ${SERVICE_USER} bash -c 'cd ${INSTALL_DIR} && .venv/bin/python3 SOPHIA.py'${NC}"
    echo ""
}

# ── main ──────────────────────────────────────────────────────────────────────

main() {
    echo -e "${BOLD}SOPHIA Installer${NC}"
    echo "========================="

    check_root
    detect_os
    install_system_deps
    check_python_version
    install_nodejs
    install_claude_code
    create_service_user
    clone_or_update_repo
    setup_virtualenv
    run_setup_wizard
    install_systemd_service
    print_banner
}

main "$@"
