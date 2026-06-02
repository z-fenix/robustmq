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

# setup.sh — Bootstrap the RobustMQ chaos test agent in a new environment.
#
# Usage:
#   cd <robustmq-project-root>
#   bash chaos-test/setup.sh
#
# What it does:
#   1. Check prerequisites (Rust >= 1.91, Python >= 3.10)
#   2. Build broker-server (release)
#   3. Copy binary to bin/
#   4. Install Python dependencies for chaos-test
#   5. Write project_root into chaos-test/config.yml
#   6. Run unit tests to verify everything works

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[setup]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
error() { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Resolve project root (must be run from repo root)
# ---------------------------------------------------------------------------
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHAOS_DIR="$PROJECT_ROOT/chaos-test"
CONFIG_YML="$CHAOS_DIR/config.yml"

if [[ ! -f "$PROJECT_ROOT/config/server.toml" ]]; then
    error "Run this script from the robustmq project root, e.g.: bash chaos-test/setup.sh"
fi

info "Project root: $PROJECT_ROOT"

# ---------------------------------------------------------------------------
# 1. Check Rust
# ---------------------------------------------------------------------------
info "Checking Rust toolchain..."
if ! command -v rustup &>/dev/null; then
    error "rustup not found. Install from https://rustup.rs"
fi

rustup update stable --no-self-update 2>&1 | grep -E "updated|unchanged|stable" || true

RUSTC_VERSION=$(rustc --version | awk '{print $2}')
REQUIRED="1.91.0"
# Compare versions: split by '.' and compare numerically
check_version() {
    local curr="$1" req="$2"
    python3 -c "
import sys
curr = tuple(int(x) for x in '$curr'.split('.')[:3])
req  = tuple(int(x) for x in '$req'.split('.')[:3])
sys.exit(0 if curr >= req else 1)
"
}
if ! check_version "$RUSTC_VERSION" "$REQUIRED"; then
    error "rustc $RUSTC_VERSION is too old, need >= $REQUIRED. Run: rustup update stable"
fi
info "Rust $RUSTC_VERSION OK"

# ---------------------------------------------------------------------------
# 2. Check Python
# ---------------------------------------------------------------------------
info "Checking Python..."
PYTHON=$(command -v python3 || command -v python || true)
if [[ -z "$PYTHON" ]]; then
    error "Python 3.10+ not found."
fi
PY_VERSION=$($PYTHON --version 2>&1 | awk '{print $2}')
if ! check_version "$PY_VERSION" "3.10.0"; then
    error "Python $PY_VERSION is too old, need >= 3.10"
fi
info "Python $PY_VERSION OK"

# ---------------------------------------------------------------------------
# 3. Build broker-server (release)
# ---------------------------------------------------------------------------
info "Building broker-server (release) — this may take 10-20 minutes on first build..."
cd "$PROJECT_ROOT"
cargo build --release -p cmd 2>&1 | grep -E "Compiling|Finished|error" || true

BINARY="$PROJECT_ROOT/target/release/broker-server"
if [[ ! -f "$BINARY" ]]; then
    error "Build failed: $BINARY not found. Check cargo output above."
fi
info "Build OK"

# ---------------------------------------------------------------------------
# 4. Copy binary to bin/
# ---------------------------------------------------------------------------
mkdir -p "$PROJECT_ROOT/bin"
cp "$BINARY" "$PROJECT_ROOT/bin/broker-server"
info "Copied binary to bin/broker-server ($(du -sh "$PROJECT_ROOT/bin/broker-server" | cut -f1))"

# ---------------------------------------------------------------------------
# 5. Install Python dependencies
# ---------------------------------------------------------------------------
info "Installing Python dependencies..."
$PYTHON -m pip install --quiet pyyaml pytest
info "Python deps OK"

# ---------------------------------------------------------------------------
# 6. Write project_root into config.yml
# ---------------------------------------------------------------------------
info "Configuring chaos-test/config.yml..."
# Use Python to update project_root in-place (preserves comments via sed)
# We use sed to replace the project_root line specifically
if grep -q "project_root:" "$CONFIG_YML"; then
    sed -i.bak "s|project_root:.*|project_root: \"$PROJECT_ROOT\"|" "$CONFIG_YML"
    rm -f "$CONFIG_YML.bak"
    info "Set project_root = $PROJECT_ROOT"
else
    warn "Could not find 'project_root' key in config.yml — set it manually."
fi

# ---------------------------------------------------------------------------
# 7. Run unit tests
# ---------------------------------------------------------------------------
info "Running chaos-test unit tests..."
cd "$CHAOS_DIR"
$PYTHON -m pytest tests/test_cluster.py -v

echo ""
info "Setup complete. To verify the cluster tool manually:"
info "  cd $CHAOS_DIR"
info "  python -c \"from tools.cluster import _action_start, _action_stop, _BROKERS; import json; _BROKERS.clear(); print(json.dumps(_action_start(), indent=2))\""
