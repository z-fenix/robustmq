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

from pathlib import Path
from unittest.mock import patch

import yaml


# ---------------------------------------------------------------------------
# _load_mqtt_credentials
# ---------------------------------------------------------------------------


def test_load_mqtt_credentials_reads_from_config(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        yaml.dump({"mqtt": {"username": "testuser", "password": "testpass"}})
    )

    from tools.client import _load_mqtt_credentials

    with patch("tools.client._CONFIG_PATH", cfg):
        user, pwd = _load_mqtt_credentials()

    assert user == "testuser"
    assert pwd == "testpass"


def test_load_mqtt_credentials_returns_empty_when_config_missing(tmp_path):
    from tools.client import _load_mqtt_credentials

    with patch("tools.client._CONFIG_PATH", tmp_path / "nonexistent.yml"):
        user, pwd = _load_mqtt_credentials()

    assert user == ""
    assert pwd == ""


def test_load_mqtt_credentials_returns_empty_when_mqtt_section_absent(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(yaml.dump({"cluster": {"binary": "bin/broker-server"}}))

    from tools.client import _load_mqtt_credentials

    with patch("tools.client._CONFIG_PATH", cfg):
        user, pwd = _load_mqtt_credentials()

    assert user == ""
    assert pwd == ""


# ---------------------------------------------------------------------------
# _run_one — MQTT credentials injected into subprocess env
# ---------------------------------------------------------------------------


def test_run_one_injects_mqtt_credentials_into_env(tmp_path):
    # _run_one looks for: _SDK_CLIENTS_DIR / sdk / scenario.sh
    (tmp_path / "python").mkdir()
    script = tmp_path / "python" / "basic-pubsub.sh"
    script.write_text(
        '#!/bin/bash\necho \'{"sent":1,"received":1,"lost":0,"p99_ms":1,"errors":[]}\'\n'
    )
    script.chmod(0o755)

    captured_env = {}

    import subprocess as _subprocess

    original_run = _subprocess.run

    def fake_run(cmd, **kwargs):
        captured_env.update(kwargs.get("env", {}))
        return original_run(
            [
                "bash",
                "-c",
                'echo \'{"sent":1,"received":1,"lost":0,"p99_ms":1,"errors":[]}\'',
            ],
            **{k: v for k, v in kwargs.items() if k != "shell"},
            shell=False,
        )

    cfg_file = tmp_path / "config.yml"
    cfg_file.write_text(
        yaml.dump({"mqtt": {"username": "myuser", "password": "mypass"}})
    )

    from tools.client import _run_one

    with patch("tools.client._SDK_CLIENTS_DIR", tmp_path), patch(
        "tools.client._CONFIG_PATH", cfg_file
    ), patch("subprocess.run", side_effect=fake_run):
        _run_one("python", "default", "basic-pubsub", "127.0.0.1:1883", 10)

    assert captured_env.get("MQTT_USERNAME") == "myuser"
    assert captured_env.get("MQTT_PASSWORD") == "mypass"


def test_run_one_does_not_inject_empty_credentials(tmp_path):
    """When config has no mqtt section, MQTT_USERNAME/PASSWORD must not appear in env."""
    (tmp_path / "python").mkdir()
    script = tmp_path / "python" / "basic-pubsub.sh"
    script.write_text(
        '#!/bin/bash\necho \'{"sent":1,"received":1,"lost":0,"p99_ms":1,"errors":[]}\'\n'
    )
    script.chmod(0o755)

    captured_env = {}

    import subprocess as _subprocess

    original_run = _subprocess.run

    def fake_run(cmd, **kwargs):
        captured_env.update(kwargs.get("env", {}))
        return original_run(
            [
                "bash",
                "-c",
                'echo \'{"sent":1,"received":1,"lost":0,"p99_ms":1,"errors":[]}\'',
            ],
            **{k: v for k, v in kwargs.items() if k != "shell"},
            shell=False,
        )

    cfg_file = tmp_path / "config.yml"
    cfg_file.write_text(yaml.dump({"cluster": {}}))  # no mqtt section

    from tools.client import _run_one

    with patch("tools.client._SDK_CLIENTS_DIR", tmp_path), patch(
        "tools.client._CONFIG_PATH", cfg_file
    ), patch("subprocess.run", side_effect=fake_run):
        _run_one("python", "default", "basic-pubsub", "127.0.0.1:1883", 10)

    assert "MQTT_USERNAME" not in captured_env
    assert "MQTT_PASSWORD" not in captured_env
