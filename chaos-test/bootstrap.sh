#!/usr/bin/env bash
# Copyright 2023 RobustMQ Team
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# bootstrap.sh — One-shot setup for RobustMQ chaos-test agent on a new machine.
#
# Usage (from anywhere):
#   bash bootstrap.sh [--project-root PATH] [--repo URL] [--mirror cn]
#
# What it does:
#   1. Collect config (interactively or from flags)
#   2. Install Rust + configure cargo mirror (optional, for CN servers)
#   3. Install Node.js if missing (needed for Claude Code)
#   4. Install Claude Code (claude CLI)
#   5. Clone / update the RobustMQ repo
#   6. Build broker-server + install Python deps (delegates to setup.sh)
#   7. Register chaos-test skill with Claude Code (delegates to hermes-setup.sh)
#   8. Smoke-test: cluster status check
#
# Flags:
#   --project-root PATH   Where to clone/find the repo (default: ~/robustmq)
#   --repo URL            Git repo URL (default: https://github.com/robustmq/robustmq)
#   --mirror cn           Enable China mirrors for Rust + npm (auto-detected if unset)
#   --skip-build          Skip cargo build (use existing binary)
#   --skip-claude         Skip Claude Code installation
#   --help                Print this message

set -euo pipefail

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${GREEN}[bootstrap]${NC} $*"; }
warn()    { echo -e "${YELLOW}[warn]${NC}  $*"; }
error()   { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }
section() { echo -e "\n${CYAN}━━━ $* ━━━${NC}"; }
ask()     { echo -e "${YELLOW}[?]${NC} $*"; }

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
PROJECT_ROOT=""
REPO_URL="https://github.com/robustmq/robustmq"
USE_MIRROR=""          # "cn" | "" (auto)
SKIP_BUILD=false
SKIP_CLAUDE=false

# ---------------------------------------------------------------------------
# Parse flags
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-root) PROJECT_ROOT="$2"; shift 2 ;;
        --repo)         REPO_URL="$2";     shift 2 ;;
        --mirror)       USE_MIRROR="$2";   shift 2 ;;
        --skip-build)   SKIP_BUILD=true;   shift ;;
        --skip-claude)  SKIP_CLAUDE=true;  shift ;;
        --help|-h)
            sed -n '/^# Usage/,/^[^#]/p' "$0" | grep '^#' | sed 's/^# \?//'
            exit 0 ;;
        *) error "Unknown flag: $1 (run with --help)" ;;
    esac
done

# ---------------------------------------------------------------------------
# Auto-detect China network (ping check)
# ---------------------------------------------------------------------------
detect_cn_network() {
    if ping -c 1 -W 2 mirrors.ustc.edu.cn &>/dev/null 2>&1; then
        echo "cn"
    else
        echo ""
    fi
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   RobustMQ Chaos-Test Agent Bootstrap            ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"
echo ""

# ---------------------------------------------------------------------------
# Step 0 — Collect config interactively
# ---------------------------------------------------------------------------
section "Step 0 — Configuration"

if [[ -z "$PROJECT_ROOT" ]]; then
    ask "Where should the RobustMQ repo live? [default: $HOME/robustmq]"
    read -r _input
    PROJECT_ROOT="${_input:-$HOME/robustmq}"
fi
PROJECT_ROOT="${PROJECT_ROOT%/}"   # strip trailing slash
info "Project root: $PROJECT_ROOT"

if [[ -z "$USE_MIRROR" ]]; then
    info "Auto-detecting network location..."
    USE_MIRROR="$(detect_cn_network)"
    if [[ "$USE_MIRROR" == "cn" ]]; then
        info "China network detected — will enable cargo + npm mirrors"
    else
        info "Non-China network — skipping mirrors"
    fi
fi

# ---------------------------------------------------------------------------
# Step 1 — Rust toolchain
# ---------------------------------------------------------------------------
section "Step 1 — Rust toolchain"

if ! command -v rustup &>/dev/null; then
    info "rustup not found — installing..."
    if [[ "$USE_MIRROR" == "cn" ]]; then
        export RUSTUP_DIST_SERVER="https://rsproxy.cn"
        export RUSTUP_UPDATE_ROOT="https://rsproxy.cn/rustup"
        info "Using rsproxy.cn for rustup"
    fi
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path
    source "$HOME/.cargo/env"
else
    info "rustup already installed ($(rustc --version))"
fi

# Ensure cargo is on PATH
[[ -f "$HOME/.cargo/env" ]] && source "$HOME/.cargo/env"
command -v cargo &>/dev/null || error "cargo not found after rustup install"

# Configure cargo mirror for CN servers
if [[ "$USE_MIRROR" == "cn" ]]; then
    CARGO_CONFIG="$HOME/.cargo/config.toml"
    if ! grep -q "rsproxy" "$CARGO_CONFIG" 2>/dev/null; then
        info "Configuring cargo mirror (rsproxy.cn)..."
        mkdir -p "$HOME/.cargo"
        cat >> "$CARGO_CONFIG" <<'TOML'

# Added by robustmq bootstrap.sh — China mirror
[source.crates-io]
replace-with = "rsproxy-sparse"

[source.rsproxy-sparse]
registry = "sparse+https://rsproxy.cn/index/"
TOML
        info "Cargo mirror configured"
    else
        info "Cargo mirror already configured"
    fi
fi

# ---------------------------------------------------------------------------
# Step 2 — Node.js (required by Claude Code)
# ---------------------------------------------------------------------------
section "Step 2 — Node.js"

install_node() {
    info "Installing Node.js via nvm..."
    if [[ "$USE_MIRROR" == "cn" ]]; then
        export NVM_NODEJS_ORG_MIRROR="https://npmmirror.com/mirrors/node"
        info "Using npmmirror.com for Node.js"
    fi
    curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
    # Load nvm for current session
    export NVM_DIR="$HOME/.nvm"
    # shellcheck disable=SC1091
    [[ -s "$NVM_DIR/nvm.sh" ]] && source "$NVM_DIR/nvm.sh"
    nvm install --lts
    nvm use --lts
}

if ! command -v node &>/dev/null; then
    install_node
else
    NODE_VER=$(node --version)
    info "Node.js $NODE_VER already installed"
    # Ensure nvm is loaded if present
    export NVM_DIR="$HOME/.nvm"
    [[ -s "$NVM_DIR/nvm.sh" ]] && source "$NVM_DIR/nvm.sh" || true
fi

# Configure npm mirror for CN
if [[ "$USE_MIRROR" == "cn" ]]; then
    if ! npm config get registry 2>/dev/null | grep -q "npmmirror"; then
        npm config set registry https://registry.npmmirror.com
        info "npm registry set to npmmirror.com"
    else
        info "npm CN mirror already configured"
    fi
fi

# ---------------------------------------------------------------------------
# Step 3 — Claude Code (claude CLI)
# ---------------------------------------------------------------------------
section "Step 3 — Claude Code (hermes)"

if [[ "$SKIP_CLAUDE" == true ]]; then
    warn "Skipping Claude Code installation (--skip-claude)"
elif command -v claude &>/dev/null; then
    info "Claude Code already installed ($(claude --version 2>/dev/null || echo 'unknown version'))"
else
    info "Installing Claude Code..."
    npm install -g @anthropic-ai/claude-code
    command -v claude &>/dev/null || error "claude not found after install — check npm global bin path"
    info "Claude Code installed: $(claude --version 2>/dev/null || echo 'ok')"
fi

# ---------------------------------------------------------------------------
# Step 4 — Clone / update RobustMQ repo
# ---------------------------------------------------------------------------
section "Step 4 — RobustMQ repository"

if [[ -d "$PROJECT_ROOT/.git" ]]; then
    info "Repo already exists at $PROJECT_ROOT — pulling latest..."
    git -C "$PROJECT_ROOT" pull --ff-only || warn "git pull failed (local changes?), continuing with existing state"
else
    info "Cloning $REPO_URL → $PROJECT_ROOT ..."
    git clone "$REPO_URL" "$PROJECT_ROOT"
fi

# Verify it's actually a RobustMQ repo
[[ -f "$PROJECT_ROOT/config/server.toml" ]] || error "Unexpected repo layout — config/server.toml not found"
info "Repo OK"

# ---------------------------------------------------------------------------
# Step 5 — Build binary + Python deps (via existing setup.sh)
# ---------------------------------------------------------------------------
section "Step 5 — Build & configure"

if [[ "$SKIP_BUILD" == true ]]; then
    warn "Skipping build (--skip-build)"
    # Still need to update config.yml project_root
    CONFIG_YML="$PROJECT_ROOT/chaos-test/config.yml"
    if grep -q "project_root:" "$CONFIG_YML"; then
        sed -i.bak "s|project_root:.*|project_root: \"$PROJECT_ROOT\"|" "$CONFIG_YML"
        rm -f "$CONFIG_YML.bak"
        info "Updated config.yml project_root = $PROJECT_ROOT"
    fi
else
    cd "$PROJECT_ROOT"
    bash chaos-test/setup.sh
fi

# ---------------------------------------------------------------------------
# Step 6 — Register skill with hermes (~/.hermes/skills/)
# ---------------------------------------------------------------------------
section "Step 6 — Register chaos-test skill with hermes"

HERMES_SKILLS_DIR="$HOME/.hermes/skills"
SKILL_LINK="$HERMES_SKILLS_DIR/robustmq-chaos-test"
CHAOS_DIR="$PROJECT_ROOT/chaos-test"

mkdir -p "$HERMES_SKILLS_DIR"

if [[ -L "$SKILL_LINK" ]]; then
    CURRENT_TARGET="$(readlink "$SKILL_LINK")"
    if [[ "$CURRENT_TARGET" == "$CHAOS_DIR" ]]; then
        info "Symlink already correct: $SKILL_LINK → $CHAOS_DIR"
    else
        warn "Updating stale symlink: $CURRENT_TARGET → $CHAOS_DIR"
        ln -sf "$CHAOS_DIR" "$SKILL_LINK"
    fi
elif [[ -e "$SKILL_LINK" ]]; then
    warn "$SKILL_LINK exists but is not a symlink — replacing with symlink"
    rm -rf "$SKILL_LINK"
    ln -s "$CHAOS_DIR" "$SKILL_LINK"
else
    ln -s "$CHAOS_DIR" "$SKILL_LINK"
    info "Created symlink: $SKILL_LINK → $CHAOS_DIR"
fi

# ---------------------------------------------------------------------------
# Step 7 — Smoke test
# ---------------------------------------------------------------------------
section "Step 7 — Smoke test"

cd "$PROJECT_ROOT/chaos-test"
STATUS=$(python3 run_tool.py cluster_manage '{"action": "status"}')
if echo "$STATUS" | python3 -m json.tool > /dev/null 2>&1; then
    info "run_tool.py smoke test OK: $STATUS"
else
    error "run_tool.py returned invalid JSON: $STATUS"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Bootstrap complete!                            ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
info "Project:     $PROJECT_ROOT"
info "Claude Code: $(command -v claude 2>/dev/null || echo 'not in PATH — open new shell')"
echo ""
info "Next steps:"
info "  1. Open a new shell (or: source ~/.cargo/env && source ~/.nvm/nvm.sh)"
info "  2. cd $PROJECT_ROOT"
info "  3. claude   ← start hermes; chaos-test skill is registered and ready"
echo ""
info "In hermes you can say:"
info "  '帮我跑一轮 RobustMQ chaos 测试'"
info "  'cluster start / stop / status'"
