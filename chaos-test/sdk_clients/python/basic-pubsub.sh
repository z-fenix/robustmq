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

set -euo pipefail

ENDPOINT="${CLUSTER_ENDPOINT:-127.0.0.1:1883}"
HOST="${ENDPOINT%%:*}"
PORT="${ENDPOINT##*:}"
MQTT_USERNAME="${MQTT_USERNAME:-admin}"
MQTT_PASSWORD="${MQTT_PASSWORD:-robustmq}"
MSG_COUNT=100
TIMEOUT=30

python3 - <<EOF
import json, time, threading, uuid, paho.mqtt.client as mqtt

host, port = "$HOST", int("$PORT")
total = $MSG_COUNT
timeout = $TIMEOUT

# Unique topic and client_id per run to avoid cross-run state conflicts in broker
run_id = uuid.uuid4().hex[:8]
topic = f"test/pubsub/{run_id}"

sent = 0
received = 0
latencies = []
errors = []
done = threading.Event()
lock = threading.Lock()

def on_connect(client, userdata, flags, rc, properties=None):
    if rc != 0:
        errors.append(f"connect failed rc={rc}")
        done.set()
        return
    client.subscribe(topic, qos=1)

def on_subscribe(client, userdata, mid, granted_qos, properties=None):
    global sent
    t0 = time.monotonic()
    for i in range(total):
        client.publish(topic, payload=f"msg-{i}", qos=1)
        sent += 1

def on_message(client, userdata, msg):
    global received
    with lock:
        received += 1
        latencies.append(time.monotonic())
    if received >= total:
        done.set()

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="chaos-test-pubsub")
client.on_connect = on_connect
client.on_subscribe = on_subscribe
client.on_message = on_message
client.username_pw_set("$MQTT_USERNAME", "$MQTT_PASSWORD")

try:
    client.connect(host, port, keepalive=60)
except Exception as e:
    print(json.dumps({"sent": 0, "received": 0, "lost": total, "p99_ms": 0, "errors": [str(e)]}))
    raise SystemExit(1)

client.loop_start()
completed = done.wait(timeout=timeout)
client.loop_stop()
client.disconnect()

lost = sent - received
if latencies and len(latencies) >= 2:
    start_t = latencies[0]
    sorted_lat = sorted((t - start_t) * 1000 for t in latencies)
    p99_ms = round(sorted_lat[int(len(sorted_lat) * 0.99)], 1)
else:
    p99_ms = 0

if not completed:
    errors.append(f"timeout after {timeout}s: sent={sent} received={received}")

print(json.dumps({"sent": sent, "received": received, "lost": lost, "p99_ms": p99_ms, "errors": errors}))

if lost > 0 or not completed:
    raise SystemExit(1)
EOF
