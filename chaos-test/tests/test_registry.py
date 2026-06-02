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

import json
import pytest
from tools.registry import registry


@pytest.fixture(autouse=True)
def clear_registry():
    registry.clear()
    yield
    registry.clear()


def test_register_tool_can_be_retrieved():
    registry.register(
        name="foo",
        toolset="chaos",
        schema={},
        handler=lambda args: "{}",
        emoji="🔧",
    )
    tools = registry.get_all()
    assert len(tools) == 1
    assert tools[0]["name"] == "foo"


def test_duplicate_name_raises_value_error():
    registry.register(
        name="foo", toolset="chaos", schema={}, handler=lambda args: "{}", emoji="🔧"
    )
    with pytest.raises(ValueError):
        registry.register(
            name="foo", toolset="chaos", schema={}, handler=lambda args: "{}", emoji="🔧"
        )


def test_handler_is_callable_and_returns_correct_value():
    registry.register(
        name="bar",
        toolset="chaos",
        schema={},
        handler=lambda args: json.dumps({"ok": True}),
        emoji="✅",
    )
    tool = registry.get_all()[0]
    result = tool["handler"]({})
    assert result == '{"ok": true}'
