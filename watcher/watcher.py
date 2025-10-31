#!/usr/bin/env python3
import os
import time
import re
import json
import requests
from collections import deque
from datetime import datetime, timedelta
from flask import Flask

# ====== CONFIG ======
LOG_PATH = "/var/log/nginx/access.log"
ACTIVE_POOL = os.environ.get("ACTIVE_POOL", "blue")
ERROR_RATE_THRESHOLD = float(os.environ.get("ERROR_RATE_THRESHOLD", 2))  # in %
WINDOW_SIZE = int(os.environ.get("WINDOW_SIZE", 200))
ALERT_COOLDOWN_SEC = int(os.environ.get("ALERT_COOLDOWN_SEC", 300))
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
MAINTENANCE_FILE = os.environ.get("MAINTENANCE_FILE", "/watcher/data/maintenance_mode")

if not SLACK_WEBHOOK_URL:
    print("ERROR: SLACK_WEBHOOK_URL not set in environment")
    exit(1)

# ====== STATE ======
request_window = deque(maxlen=WINDOW_SIZE)
last_failover_pool = ACTIVE_POOL
last_failover_alert = datetime.min
last_error_rate_alert = datetime.min
error_rate_breached = False
maintenance_mode_prev = False  # Track previous state to detect changes

LOG_REGEX = re.compile(
    r'.*pool:(?P<pool>\w+)\s+release:(?P<release>[\w\-]+)\s+upstream_status:(?P<upstream_status>\d+)'
)

# ====== HELPERS ======
def log_console(message: str):
    from datetime import datetime, timezone
    print(f"[{datetime.now(timezone.utc).isoformat()}] {message}", flush=True)

def send_slack_alert(message: str, alert_type="info", pool=None, error_rate=None):
    if os.path.exists(MAINTENANCE_FILE):
        log_console(f"(MAINTENANCE MODE) Suppressed alert: {message}")
        return

    color_map = {
        "failover": "#FF0000",
        "error_rate": "#FFA500",
        "info": "#36C5F0"
    }

    emoji_map = {
        "failover": "🚨",
        "error_rate": " ",
        "info": " "
    }

    title_map = {
        "failover": "*Failover Detected!*",
        "error_rate": "*High Error Rate Detected!*",
        "info": "*Alert Notification*"
    }

    color = color_map.get(alert_type, "#36C5F0")
    emoji = emoji_map.get(alert_type, "💡")
    title = title_map.get(alert_type, "*Alert Notification*")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{emoji} {title}", "emoji": True}
        },
        {"type": "section", "fields": []},
        {"type": "section", "text": {"type": "mrkdwn", "text": message}},
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"🕒 *Timestamp:* {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}"}
            ]
        }
    ]

    if pool:
        blocks[1]["fields"].append({"type": "mrkdwn", "text": f"*Active Pool:*\n`{pool}`"})
    if error_rate is not None:
        filled = int(error_rate // 5)
        bar = "█" * filled + "░" * (20 - filled)
        blocks[1]["fields"].append({"type": "mrkdwn", "text": f"*Error Rate:*\n`{error_rate:.2f}%`\n{bar}"})

    payload = {"blocks": blocks, "attachments": [{"color": color}]}

    try:
        resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=5)
        resp.raise_for_status()
        log_console(f"✅ Slack alert sent: {alert_type.upper()}")
    except Exception as e:
        log_console(f"❌ Failed to send Slack alert: {e}")

def tail(f):
    f.seek(0, 2)
    while True:
        line = f.readline()
        if not line:
            time.sleep(0.1)
            continue
        yield line.strip()

# ====== MAIN LOOP ======
def watch_logs():
    global last_failover_pool, last_failover_alert, last_error_rate_alert, error_rate_breached, maintenance_mode_prev

    log_console(f"Starting alert watcher on {LOG_PATH}")
    with open(LOG_PATH, "r") as f:
        for line in tail(f):
            maintenance_mode_current = os.path.exists(MAINTENANCE_FILE)
            if maintenance_mode_current != maintenance_mode_prev:
                if maintenance_mode_current:
                    send_slack_alert("🛠️ *Maintenance mode ENABLED — alerts suppressed*", alert_type="info")
                else:
                    send_slack_alert("✅ *Maintenance mode DISABLED — alerts resumed*", alert_type="info")
                maintenance_mode_prev = maintenance_mode_current

            match = LOG_REGEX.search(line)
            if not match:
                continue

            pool = match.group("pool")
            upstream_status = int(match.group("upstream_status"))
            request_window.append(upstream_status)
            now = datetime.utcnow()

            if pool != last_failover_pool:
                if (now - last_failover_alert).total_seconds() >= ALERT_COOLDOWN_SEC:
                    send_slack_alert(
                        f"Failover detected! Pool switched from `{last_failover_pool}` → `{pool}`",
                        alert_type="failover",
                        pool=pool
                    )
                    last_failover_alert = now
                last_failover_pool = pool

            elif pool == ACTIVE_POOL and last_failover_pool != ACTIVE_POOL:
                if (now - last_failover_alert).total_seconds() >= ALERT_COOLDOWN_SEC:
                    send_slack_alert(
                        f"Primary pool `{ACTIVE_POOL}` is now serving traffic again.",
                        alert_type="info",
                        pool=ACTIVE_POOL
                    )
                    last_failover_alert = now
                last_failover_pool = ACTIVE_POOL

            if len(request_window) == WINDOW_SIZE:
                error_count = sum(1 for s in request_window if 500 <= s <= 599)
                error_rate = (error_count / WINDOW_SIZE) * 100
                log_console(f"Error rate: {error_rate:.2f}% ({error_count} errors)")

                if error_rate > ERROR_RATE_THRESHOLD:
                    if not error_rate_breached and (now - last_error_rate_alert).total_seconds() >= ALERT_COOLDOWN_SEC:
                        send_slack_alert(
                            f"High error rate detected: {error_rate:.2f}% 5xx responses over last {WINDOW_SIZE} requests",
                            alert_type="error_rate",
                            pool=ACTIVE_POOL,
                            error_rate=error_rate
                        )
                        last_error_rate_alert = now
                        error_rate_breached = True
                elif error_rate_breached and (now - last_error_rate_alert).total_seconds() >= ALERT_COOLDOWN_SEC:
                    send_slack_alert(
                        f"Error rate recovered: {error_rate:.2f}% 5xx responses over last {WINDOW_SIZE} requests",
                        alert_type="info",
                        pool=ACTIVE_POOL,
                        error_rate=error_rate
                    )
                    last_error_rate_alert = now
                    error_rate_breached = False

# ====== FLASK CHAOS MODE ENDPOINT ======
app = Flask(__name__)

@app.route('/chaos_mode/on', methods=['POST'])
def chaos_mode():
    send_slack_alert("Chaos mode triggered manually via HTTP", alert_type="info")
    return "Chaos mode activated", 200

if __name__ == "__main__":
    import threading
    threading.Thread(target=watch_logs, daemon=True).start()
    app.run(host="0.0.0.0", port=3000)
