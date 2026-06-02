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

import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def test_load_config_reads_cluster_section(tmp_path):
    cfg_file = tmp_path / "config.yml"
    cfg_file.write_text(
        yaml.dump(
            {
                "cluster": {
                    "binary": "bin/broker-server",
                    "project_root": "",
                    "mode": "single",
                    "single": {
                        "config": "config/server.toml",
                        "data_dir": "data",
                        "mqtt_port": 1883,
                    },
                }
            }
        )
    )
    from tools.cluster import _load_config

    result = _load_config(cfg_file)
    assert "error" not in result
    assert result["binary"] == "bin/broker-server"
    assert result["mode"] == "single"


def test_load_config_error_when_binary_empty(tmp_path):
    cfg_file = tmp_path / "config.yml"
    cfg_file.write_text(
        yaml.dump({"cluster": {"binary": "", "mode": "single", "single": {}}})
    )
    from tools.cluster import _load_config

    result = _load_config(cfg_file)
    assert "error" in result


def test_load_config_error_when_file_missing(tmp_path):
    from tools.cluster import _load_config

    result = _load_config(tmp_path / "nonexistent.yml")
    assert "error" in result


# ---------------------------------------------------------------------------
# project_root resolution
# ---------------------------------------------------------------------------


def test_resolve_project_root_finds_by_config_toml(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "server.toml").write_text("")
    from tools.cluster import _resolve_project_root

    result = _resolve_project_root("", start=tmp_path)
    assert result == tmp_path


def test_resolve_project_root_uses_explicit_value(tmp_path):
    from tools.cluster import _resolve_project_root

    result = _resolve_project_root(str(tmp_path))
    assert result == tmp_path


def test_resolve_project_root_returns_none_when_not_found(tmp_path):
    from tools.cluster import _resolve_project_root

    result = _resolve_project_root("", start=tmp_path)
    assert result is None


# ---------------------------------------------------------------------------
# start — single mode
# ---------------------------------------------------------------------------


def _make_single_cfg(tmp_path):
    toml = tmp_path / "server.toml"
    toml.write_text("")
    binary = tmp_path / "broker-server"
    binary.write_text("")
    binary.chmod(0o755)
    return {
        "binary": str(binary),
        "project_root": str(tmp_path),
        "mode": "single",
        "single": {
            "config": str(toml),
            "data_dir": str(tmp_path / "data"),
            "mqtt_port": 11883,
        },
    }


def test_start_single_node_spawns_one_process(tmp_path):
    cfg = _make_single_cfg(tmp_path)
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    from tools.cluster import _BROKERS, _action_start

    _BROKERS.clear()
    with patch("tools.cluster._load_config", return_value=cfg), patch(
        "subprocess.Popen", return_value=mock_proc
    ), patch("tools.cluster._health_check", return_value=True):
        result = _action_start()

    assert result.get("status") == "running"
    assert len(result.get("nodes", [])) == 1
    assert len(_BROKERS) == 1
    _BROKERS.clear()


def test_start_returns_error_when_config_file_missing(tmp_path):
    binary = tmp_path / "broker-server"
    binary.write_text("")
    binary.chmod(0o755)
    cfg = {
        "binary": str(binary),
        "project_root": str(tmp_path),
        "mode": "single",
        "single": {
            "config": str(tmp_path / "nonexistent.toml"),
            "data_dir": str(tmp_path / "data"),
            "mqtt_port": 11883,
        },
    }
    from tools.cluster import _BROKERS, _action_start

    _BROKERS.clear()
    with patch("tools.cluster._load_config", return_value=cfg):
        result = _action_start()

    assert "error" in result
    _BROKERS.clear()


def test_start_returns_error_when_binary_missing(tmp_path):
    toml = tmp_path / "server.toml"
    toml.write_text("")
    cfg = {
        "binary": str(tmp_path / "no-binary"),
        "project_root": str(tmp_path),
        "mode": "single",
        "single": {
            "config": str(toml),
            "data_dir": str(tmp_path / "data"),
            "mqtt_port": 11883,
        },
    }
    from tools.cluster import _BROKERS, _action_start

    _BROKERS.clear()
    with patch("tools.cluster._load_config", return_value=cfg):
        result = _action_start()

    assert "error" in result
    assert "broker-server" in result["error"]
    _BROKERS.clear()


def test_start_returns_error_when_already_running(tmp_path):
    from tools.cluster import _BROKERS, _action_start

    _BROKERS["broker-1"] = {
        "process": MagicMock(),
        "mqtt_port": 1883,
        "data_dir": str(tmp_path),
    }
    result = _action_start()
    assert "error" in result
    assert "already running" in result["error"]
    _BROKERS.clear()


# ---------------------------------------------------------------------------
# start — multi mode
# ---------------------------------------------------------------------------


def _make_multi_cfg(tmp_path):
    binary = tmp_path / "broker-server"
    binary.write_text("")
    binary.chmod(0o755)
    nodes = []
    for i in range(1, 4):
        toml = tmp_path / f"server-{i}.toml"
        toml.write_text("")
        nodes.append(
            {
                "config": str(toml),
                "data_dir": str(tmp_path / f"data/broker-{i}"),
                "mqtt_port": 10000 + i,
            }
        )
    return {
        "binary": str(binary),
        "project_root": str(tmp_path),
        "mode": "multi",
        "multi": {"nodes": nodes},
    }


def test_start_multi_node_spawns_three_processes(tmp_path):
    cfg = _make_multi_cfg(tmp_path)
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    from tools.cluster import _BROKERS, _action_start

    _BROKERS.clear()
    with patch("tools.cluster._load_config", return_value=cfg), patch(
        "subprocess.Popen", return_value=mock_proc
    ), patch("tools.cluster._health_check", return_value=True):
        result = _action_start()

    assert result.get("status") == "running"
    assert len(result.get("nodes", [])) == 3
    assert len(_BROKERS) == 3
    _BROKERS.clear()


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


def test_stop_returns_stopped_when_no_cluster_running():
    from tools.cluster import _BROKERS, _action_stop

    _BROKERS.clear()
    with patch("tools.cluster._kill_stray_brokers", return_value=0), patch(
        "tools.cluster._load_config", return_value={"error": "no config"}
    ):
        result = _action_stop()
    assert result["status"] == "stopped"


def test_stop_kills_processes_and_removes_data_dirs(tmp_path):
    data_dir = tmp_path / "broker-data"
    data_dir.mkdir()

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    from tools.cluster import _BROKERS, _action_stop

    _BROKERS.clear()
    _BROKERS["broker-1"] = {
        "process": mock_proc,
        "mqtt_port": 1883,
        "data_dir": str(data_dir),
    }

    with patch("tools.cluster._kill_stray_brokers", return_value=0):
        result = _action_stop()

    assert result["status"] == "stopped"
    assert not data_dir.exists()
    assert len(_BROKERS) == 0
    mock_proc.kill.assert_called_once()


def test_stop_kills_stray_processes_when_brokers_dict_empty(tmp_path):
    """After external SIGKILL the _BROKERS dict is empty; stop must still kill strays."""
    from tools.cluster import _BROKERS, _action_stop

    _BROKERS.clear()
    with patch("tools.cluster._kill_stray_brokers", return_value=1) as mock_kill, patch(
        "tools.cluster._load_config", return_value={"error": "no config"}
    ):
        result = _action_stop()

    assert result["status"] == "stopped"
    mock_kill.assert_called_once()


def test_stop_cleans_config_data_dirs_when_brokers_dict_empty(tmp_path):
    """When _BROKERS is empty, stop falls back to config-defined data dirs for cleanup."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    cfg = {
        "binary": "bin/broker-server",
        "project_root": str(tmp_path),
        "mode": "single",
        "single": {
            "config": str(tmp_path / "server.toml"),
            "data_dir": "data",
            "mqtt_port": 1883,
        },
    }

    from tools.cluster import _BROKERS, _action_stop

    _BROKERS.clear()
    with patch("tools.cluster._kill_stray_brokers", return_value=0), patch(
        "tools.cluster._load_config", return_value=cfg
    ):
        result = _action_stop()

    assert result["status"] == "stopped"
    assert str(data_dir) in result["cleaned_dirs"]
    assert not data_dir.exists()


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_running_when_all_alive():
    from tools.cluster import _BROKERS, _action_status

    _BROKERS.clear()
    for name in ["broker-1", "broker-2"]:
        proc = MagicMock()
        proc.poll.return_value = None
        _BROKERS[name] = {"process": proc, "mqtt_port": 1883, "data_dir": "/tmp/x"}

    result = _action_status()
    assert result["status"] == "running"
    assert result["running_processes"] == 2
    _BROKERS.clear()


def test_status_degraded_when_some_dead():
    from tools.cluster import _BROKERS, _action_status

    _BROKERS.clear()
    alive = MagicMock()
    alive.poll.return_value = None
    dead = MagicMock()
    dead.poll.return_value = 0

    _BROKERS["broker-1"] = {"process": alive, "mqtt_port": 1883, "data_dir": "/tmp/x"}
    _BROKERS["broker-2"] = {"process": dead, "mqtt_port": 2883, "data_dir": "/tmp/y"}

    result = _action_status()
    assert result["status"] == "degraded"
    _BROKERS.clear()
