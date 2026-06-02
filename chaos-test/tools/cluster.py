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
cluster.py — RobustMQ test cluster lifecycle tool.

Reads cluster configuration from chaos-test/config.yml.
Supports single-node and multi-node modes.
Uses existing TOML config files from the RobustMQ project directly —
no TOML generation. Data dirs are created on start and removed on stop.

Fill in config.yml:
  cluster.binary       — path to broker-server binary (relative to project_root or absolute)
  cluster.project_root — path to robustmq project root (leave empty to auto-detect)
  cluster.mode         — "single" or "multi"
"""

import json
import logging
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Optional

import yaml

from tools.registry import registry

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "config.yml"

_BROKERS: dict = {}

_HEALTH_TIMEOUT = 60
_HEALTH_INTERVAL = 2


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _load_config(path=_CONFIG_PATH) -> dict:
    try:
        with open(path) as f:
            raw = yaml.safe_load(f)
    except FileNotFoundError:
        return {"error": f"config file not found: {path}"}
    except Exception as exc:
        return {"error": f"failed to read config: {exc}"}

    cfg = (raw or {}).get("cluster")
    if not cfg:
        return {"error": "config.yml is missing 'cluster' section"}

    if not cfg.get("binary", "").strip():
        return {"error": "'cluster.binary' must not be empty in config.yml"}

    return cfg


def _resolve_project_root(explicit: str, start: Path = None) -> Optional[Path]:
    if explicit and explicit.strip():
        return Path(explicit.strip())

    base = start or Path(__file__).parent
    for candidate in [base] + list(base.parents):
        if (candidate / "config" / "server.toml").is_file():
            return candidate
    return None


def _node_list(cfg: dict, root: Path) -> list:
    mode = cfg.get("mode", "single")

    def resolve(p: str) -> Path:
        p = p.strip()
        if Path(p).is_absolute():
            return Path(p)
        return root / p

    if mode == "multi":
        nodes = cfg.get("multi", {}).get("nodes", [])
        return [
            {
                "name": f"broker-{i + 1}",
                "config_path": resolve(n["config"]),
                "data_dir": resolve(n["data_dir"]),
                "mqtt_port": n["mqtt_port"],
            }
            for i, n in enumerate(nodes)
        ]
    else:
        single = cfg.get("single", {})
        return [
            {
                "name": "broker-1",
                "config_path": resolve(single["config"]),
                "data_dir": resolve(single["data_dir"]),
                "mqtt_port": single["mqtt_port"],
            }
        ]


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


def _health_check(mqtt_port: int) -> bool:
    """Verify MQTT readiness by sending a raw CONNECT and waiting for any CONNACK.
    Any CONNACK (including rc=5 not-authorized) means the MQTT service is live.
    A plain TCP check can succeed before the MQTT handler is initialized."""
    try:
        # MQTT v3.1.1 CONNECT: clean_session, client_id="rmq-probe", no auth
        # Fixed header + remaining(21) + protocol name + level + flags + keepalive + client_id
        packet = (
            b"\x10\x15"  # CONNECT, remaining=21
            b"\x00\x04MQTT"  # protocol name
            b"\x04"  # protocol level 3.1.1
            b"\x02"  # connect flags: clean session
            b"\x00\x0a"  # keep alive 10s
            b"\x00\x09rmq-probe"  # client ID length + value
        )
        with socket.create_connection(("127.0.0.1", mqtt_port), timeout=2) as sock:
            sock.sendall(packet)
            data = sock.recv(4)
            return (
                len(data) >= 2 and data[0] == 0x20
            )  # any CONNACK means service is ready
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def _grpc_ready(grpc_port: int) -> bool:
    """Check if GRPC port is listening."""
    try:
        with socket.create_connection(("127.0.0.1", grpc_port), timeout=2) as sock:
            return True
    except OSError:
        return False


def _action_start() -> dict:
    if _BROKERS:
        return {
            "error": "Cluster is already running. Call stop first if you want to restart."
        }

    cfg = _load_config()
    if "error" in cfg:
        return cfg

    root = _resolve_project_root(cfg.get("project_root", ""))
    if root is None:
        return {
            "error": "Cannot locate project root. Set 'cluster.project_root' in config.yml."
        }

    binary_rel = cfg["binary"].strip()
    binary = Path(binary_rel) if Path(binary_rel).is_absolute() else root / binary_rel
    if not binary.is_file():
        return {
            "error": (
                f"broker-server binary not found at {binary}. "
                "Check 'cluster.binary' in config.yml."
            )
        }

    nodes = _node_list(cfg, root)

    for node in nodes:
        if not node["config_path"].is_file():
            return {
                "error": (
                    f"Config file not found for {node['name']}: {node['config_path']}. "
                    "Check 'cluster.mode' and paths in config.yml."
                )
            }

    started = []
    for node in nodes:
        node["data_dir"].mkdir(parents=True, exist_ok=True)
        log_file = node["data_dir"] / "broker.log"
        try:
            with open(log_file, "w") as lf:
                proc = subprocess.Popen(
                    [str(binary), "--conf", str(node["config_path"])],
                    stdout=lf,
                    stderr=subprocess.STDOUT,
                    close_fds=True,
                    cwd=str(root),
                )
        except OSError as exc:
            for s in started:
                try:
                    _BROKERS[s]["process"].kill()
                except Exception:
                    pass
            _BROKERS.clear()
            return {"error": f"Failed to start {node['name']}: {exc}"}

        _BROKERS[node["name"]] = {
            "process": proc,
            "mqtt_port": node["mqtt_port"],
            "data_dir": str(node["data_dir"]),
        }
        started.append(node["name"])

    # Phase 2: Health check all nodes (parallel) - wait for MQTT to be ready
    for node in nodes:
        deadline = time.monotonic() + _HEALTH_TIMEOUT
        while time.monotonic() < deadline:
            if _health_check(node["mqtt_port"]):
                break
            time.sleep(_HEALTH_INTERVAL)
        else:
            data_dirs = [info["data_dir"] for info in _BROKERS.values()]
            for info in _BROKERS.values():
                try:
                    info["process"].kill()
                    info["process"].wait(timeout=5)
                except Exception:
                    pass
            _BROKERS.clear()
            for d in data_dirs:
                shutil.rmtree(d, ignore_errors=True)
            return {
                "status": "failed",
                "error": (
                    f"Health check failed for {node['name']} after {_HEALTH_TIMEOUT}s. "
                    f"Check logs: {node['data_dir']}/broker.log"
                ),
            }

    endpoints = [f"127.0.0.1:{n['mqtt_port']}" for n in nodes]
    return {
        "status": "running",
        "endpoint": endpoints[0],
        "endpoints": endpoints,
        "nodes": list(_BROKERS.keys()),
    }


def _kill_stray_brokers(binary: str) -> int:
    """Kill any broker-server processes not tracked in _BROKERS (e.g. after external SIGKILL).
    Returns the number of stray processes killed."""
    killed = 0
    try:
        result = subprocess.run(["pgrep", "-f", binary], capture_output=True, text=True)
        for pid_str in result.stdout.splitlines():
            try:
                pid = int(pid_str.strip())
                subprocess.run(["kill", "-9", str(pid)], check=False)
                killed += 1
            except (ValueError, OSError):
                pass
        if killed:
            time.sleep(1)  # wait for OS to reclaim ports
    except OSError:
        pass
    return killed


def _action_stop() -> dict:
    cfg = _load_config()
    binary_name = (
        Path(cfg.get("binary", "broker-server")).name
        if "error" not in cfg
        else "broker-server"
    )

    # Collect tracked data dirs; fall back to config-defined dirs so stop works
    # even when called in a fresh process (after external SIGKILL, for example).
    data_dirs = [info["data_dir"] for info in _BROKERS.values()]
    if not data_dirs and "error" not in cfg:
        root = _resolve_project_root(cfg.get("project_root", ""))
        if root:
            try:
                for node in _node_list(cfg, root):
                    d = str(node["data_dir"])
                    if Path(d).exists():
                        data_dirs.append(d)
            except Exception:
                pass

    for name, info in list(_BROKERS.items()):
        proc = info.get("process")
        if proc and proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception as exc:
                logger.warning("cluster: failed to kill %s: %s", name, exc)
    _BROKERS.clear()

    stray = _kill_stray_brokers(binary_name)
    if stray:
        logger.info("cluster: killed %d stray broker process(es)", stray)

    for d in data_dirs:
        try:
            shutil.rmtree(d, ignore_errors=True)
        except Exception as exc:
            logger.warning("cluster: failed to remove data dir %s: %s", d, exc)

    return {"status": "stopped", "cleaned_dirs": data_dirs}


def _action_status() -> dict:
    if not _BROKERS:
        return {"status": "stopped", "running_processes": 0, "endpoint": None}

    alive = []
    dead = []
    for name, info in _BROKERS.items():
        proc = info.get("process")
        if proc and proc.poll() is None:
            alive.append(name)
        else:
            dead.append(name)

    if not alive:
        status = "stopped"
    elif dead:
        status = "degraded"
    else:
        status = "running"

    endpoints = [f"127.0.0.1:{info['mqtt_port']}" for info in _BROKERS.values()]
    return {
        "status": status,
        "running_processes": len(alive),
        "total_processes": len(_BROKERS),
        "alive_nodes": alive,
        "dead_nodes": dead,
        "endpoint": f"127.0.0.1:{list(_BROKERS.values())[0]['mqtt_port']}"
        if alive
        else None,
        "endpoints": endpoints,
    }


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------


def _cluster_handler(args: dict, **_) -> str:
    action = args.get("action", "")
    try:
        if action == "start":
            result = _action_start()
        elif action == "stop":
            result = _action_stop()
        elif action == "status":
            result = _action_status()
        else:
            result = {
                "error": f"unknown action: '{action}'. Valid: start, stop, status"
            }
    except Exception as exc:
        logger.exception("cluster: unhandled error in action '%s'", action)
        result = {"error": f"internal error: {exc}"}
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Schema + registration
# ---------------------------------------------------------------------------

_SCHEMA: dict = {
    "name": "cluster_manage",
    "description": (
        "Start, stop, or query the RobustMQ test cluster. "
        "Reads configuration from chaos-test/config.yml. "
        "Supports single-node and multi-node modes. "
        "start: launches broker(s) using existing TOML configs, health-checks each MQTT port. "
        "stop: kills all brokers and removes their data dirs. "
        "status: returns per-node liveness."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start", "stop", "status"],
                "description": (
                    "start: spawn brokers and wait for health. "
                    "stop: kill all brokers and clean up data dirs. "
                    "status: check which broker processes are alive."
                ),
            },
        },
        "required": ["action"],
    },
}

registry.register(
    name="cluster_manage",
    toolset="chaos",
    schema=_SCHEMA,
    handler=_cluster_handler,
    emoji="🖥️",
)
