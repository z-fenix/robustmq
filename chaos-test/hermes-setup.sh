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

# hermes-setup.sh — Register the RobustMQ chaos-test skill with Hermes (Claude Code).
#
# Usage:
#   cd <robustmq-project-root>
#   bash chaos-test/hermes-setup.sh
#
# What it does:
#   1. Run setup.sh (build binary, install Python deps, configure config.yml)
#   2. Copy SKILL.md into the Claude Code skills directory
#   3. Add run_tool.py permission to .claude/settings.json
#   4. Verify the entry point works

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[hermes-setup]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
error() { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHAOS_DIR="$PROJECT_ROOT/chaos-test"
CLAUDE_DIR="$PROJECT_ROOT/.claude"
SKILLS_DIR="$CLAUDE_DIR/skills"
SKILL_NAME="robustmq-chaos-test"

if [[ ! -f "$PROJECT_ROOT/config/server.toml" ]]; then
    error "Run this script from the robustmq project root, e.g.: bash chaos-test/hermes-setup.sh"
fi

# ---------------------------------------------------------------------------
# 1. Run setup.sh
# ---------------------------------------------------------------------------
info "Running setup.sh (build + configure)..."
bash "$CHAOS_DIR/setup.sh"

# ---------------------------------------------------------------------------
# 2. Register skill with Claude Code (Hermes)
# ---------------------------------------------------------------------------
info "Registering skill '$SKILL_NAME' with Hermes..."
SKILL_DEST="$SKILLS_DIR/$SKILL_NAME"
mkdir -p "$SKILL_DEST"
cp "$CHAOS_DIR/SKILL.md" "$SKILL_DEST/SKILL.md"
info "Copied SKILL.md → $SKILL_DEST/SKILL.md"

# ---------------------------------------------------------------------------
# 3. Add run_tool.py permission to .claude/settings.json
# ---------------------------------------------------------------------------
SETTINGS="$CLAUDE_DIR/settings.json"
RUN_TOOL_PERMISSION="Bash(python*chaos-test/run_tool.py*)"

if [[ ! -f "$SETTINGS" ]]; then
    warn "settings.json not found at $SETTINGS — skipping permission update"
else
    if grep -q "run_tool.py" "$SETTINGS"; then
        info "run_tool.py permission already in settings.json"
    else
        # Insert permission using Python (safe JSON edit)
        python3 - "$SETTINGS" "$RUN_TOOL_PERMISSION" <<'EOF'
import json, sys
path, perm = sys.argv[1], sys.argv[2]
with open(path) as f:
    data = json.load(f)
allow = data.setdefault("permissions", {}).setdefault("allow", [])
if perm not in allow:
    allow.append(perm)
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
EOF
        info "Added run_tool.py permission to settings.json"
    fi
fi

# ---------------------------------------------------------------------------
# 4. Verify entry point
# ---------------------------------------------------------------------------
info "Verifying run_tool.py entry point..."
cd "$CHAOS_DIR"
python3 run_tool.py cluster_manage '{"action": "status"}' | python3 -m json.tool > /dev/null \
    && info "run_tool.py OK" \
    || error "run_tool.py returned invalid output"

echo ""
info "Hermes setup complete!"
info ""
info "In Hermes, you can now say:"
info "  '帮我验证一下 cluster_manage 工具，依次调用 start、status、stop'"
info ""
info "Or Hermes calls the tool directly via:"
info "  cd $CHAOS_DIR && python3 run_tool.py cluster_manage '{\"action\": \"start\"}'"
