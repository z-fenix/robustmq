#!/usr/bin/env python3
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

"""
run_tool.py — Entry point for Hermes (Claude Code) to invoke chaos-test tools.

Usage:
    python run_tool.py <tool_name> '<json_args>'

Examples:
    python run_tool.py cluster_manage '{"action": "start"}'
    python run_tool.py cluster_manage '{"action": "status"}'
    python run_tool.py cluster_manage '{"action": "stop"}'
"""

import json
import sys
import os

# Ensure chaos-test/ is on sys.path regardless of cwd
sys.path.insert(0, os.path.dirname(__file__))

# Import all tool modules so they register themselves
from tools import cluster  # noqa: F401
from tools import chaos  # noqa: F401
from tools import client  # noqa: F401
from tools import observability  # noqa: F401
from tools import report  # noqa: F401
from tools.registry import registry


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: run_tool.py <tool_name> '<json_args>'"}))
        sys.exit(1)

    tool_name = sys.argv[1]
    raw_args = sys.argv[2] if len(sys.argv) > 2 else "{}"

    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON args: {e}"}))
        sys.exit(1)

    tools = {t["name"]: t for t in registry.get_all()}
    if tool_name not in tools:
        available = list(tools.keys())
        print(
            json.dumps({"error": f"Unknown tool '{tool_name}'. Available: {available}"})
        )
        sys.exit(1)

    result = tools[tool_name]["handler"](args)
    print(result)


if __name__ == "__main__":
    main()
