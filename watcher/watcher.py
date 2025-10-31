#!/usr/bin/env python3
import os
import time
import re
import requests
from collections import deque
from datetime import datetime, timezone

# ====== CONFIG ======
LOG_PATH = "/var/log/nginx/access.log"
ACTIVE_POOL = os.environ.get("ACTIVE_POOL", "blue")
ERROR_RATE_THRESHOLD = float(os.environ.get("ERROR_RATE_THRESHOLD", 2))  # %
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
maintenance_mode_prev = False

LOG_REGEX = re.compile(
    r'.*pool:(?P<pool>\w+)\s+release:(?P<release>[\w\-]+)\s+upstream_status:(?P<upstream_status>\d+)'
)

# ====== HELPERS ======
def log_console(message: str):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {message}", flush=True)

def send_slack_alert(title: str, message: str, alert_type: str = "info", pool=None, error_rate=None):
    """Send styled Slack alert using Block Kit"""
    if os.path.exists(MAINTENANCE_FILE):
        log_console(f"(MAINTENANCE MODE) Suppressed alert: {title}")
        return

    emoji_map = {
        "info": "🟢",
        "error_rate": "🟠",
        "failover": "🚨",
    }
    emoji = emoji_map.get(alert_type, "ℹ️")

    color_map = {
        "info": "#36C5F0",
        "error_rate": "#FFA500",
        "failover": "#FF0000",
    }
    color = color_map.get(alert_type, "#36C5F0")

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    config_section = (
        f"*Configuration:*\n"
        f"• *Monitoring:* `{LOG_PATH}`\n"
        f"• *Error Threshold:* `{ERROR_RATE_THRESHOLD:.1f}%`\n"
        f"• *Window Size:* `{WINDOW_SIZE}` requests\n"
        f"• *Cooldown Period:* `{ALERT_COOLDOWN_SEC}s`\n"
        f"• *Primary Pool:* `{ACTIVE_POOL}`\n"
        f"• *Backup Pool:* `green`"
    )

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{emoji} {title}", "emoji": True},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": message},
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": config_section},
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"*Timestamp:* {timestamp} | *Alert Type:* `{alert_type}`"}
            ],
        },
    ]

    if error_rate is not None:
        bar_fill = int(error_rate // 5)
        bar = "█" * bar_fill + "░" * (20 - bar_fill)
        blocks.insert(2, {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Error Rate:* `{error_rate:.2f}%`\n{bar}"}
            ],
        })

    payload = {"attachments": [{"color": color, "blocks": blocks}]}

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
def main():
    global last_failover_pool, last_failover_alert, last_error_rate_alert, error_rate_breached, maintenance_mode_prev

    log_console(f"Starting alert watcher on {LOG_PATH}")
    send_slack_alert(
        title="blue-green-app-BG Alert",
        message="🟢 *Alert Watcher Started*\n\nStatus: Monitoring active. Ready to detect failovers and error spikes.",
        alert_type="info"
    )

    with open(LOG_PATH, "r") as f:
        for line in tail(f):
            # ====== Maintenance Mode ======
            maintenance_mode_current = os.path.exists(MAINTENANCE_FILE)
            if maintenance_mode_current != maintenance_mode_prev:
                if maintenance_mode_current:
                    send_slack_alert("Maintenance Mode", "🛠️ *Enabled — alerts suppressed.*", "info")
                else:
                    send_slack_alert("Maintenance Mode", "✅ *Disabled — alerts resumed.*", "info")
                maintenance_mode_prev = maintenance_mode_current

            match = LOG_REGEX.search(line)
            if not match:
                continue

            pool = match.group("pool")
            upstream_status = int(match.group("upstream_status"))
            request_window.append(upstream_status)
            now = datetime.utcnow()

            # ====== FAILOVER DETECTION ======
            if pool != last_failover_pool:
                if (now - last_failover_alert).total_seconds() >= ALERT_COOLDOWN_SEC:
                    send_slack_alert(
                        title="FAILOVER DETECTED",
                        message=f"*Pool Changed:* `{last_failover_pool}` → `{pool}`\n"
                                f"*Trigger:* High error rate in `{last_failover_pool}` pool\n"
                                f"*Action:* Failover completed automatically\n"
                                f"*Status:* System recovered and serving traffic from `{pool}` pool",
                        alert_type="failover",
                        pool=pool,
                    )
                    last_failover_alert = now
                last_failover_pool = pool

            # ====== FAILOVER RECOVERY ======
            elif pool == ACTIVE_POOL and last_failover_pool != ACTIVE_POOL:
                if (now - last_failover_alert).total_seconds() >= ALERT_COOLDOWN_SEC:
                    send_slack_alert(
                        title="Failover Recovery",
                        message=f"✅ Primary pool `{ACTIVE_POOL}` is now serving traffic again.",
                        alert_type="info",
                        pool=ACTIVE_POOL,
                    )
                    last_failover_alert = now
                last_failover_pool = ACTIVE_POOL

            # ====== ERROR RATE DETECTION ======
            if len(request_window) == WINDOW_SIZE:
                error_count = sum(1 for s in request_window if 500 <= s <= 599)
                error_rate = (error_count / WINDOW_SIZE) * 100
                log_console(f"Error rate: {error_rate:.2f}% ({error_count} errors)")

                # High error rate
                if error_rate > ERROR_RATE_THRESHOLD:
                    if not error_rate_breached and (now - last_error_rate_alert).total_seconds() >= ALERT_COOLDOWN_SEC:
                        send_slack_alert(
                            title="High Error Rate Detected",
                            message=f"Detected *{error_rate:.2f}%* 5xx responses over the last *{WINDOW_SIZE}* requests.",
                            alert_type="error_rate",
                            pool=ACTIVE_POOL,
                            error_rate=error_rate,
                        )
                        last_error_rate_alert = now
                        error_rate_breached = True

                # Recovery
                elif error_rate_breached and (now - last_error_rate_alert).total_seconds() >= ALERT_COOLDOWN_SEC:
                    send_slack_alert(
                        title="Error Rate Recovered",
                        message=f"Error rate recovered to *{error_rate:.2f}%* over last *{WINDOW_SIZE}* requests.",
                        alert_type="info",
                        pool=ACTIVE_POOL,
                        error_rate=error_rate,
                    )
                    last_error_rate_alert = now
                    error_rate_breached = False

if __name__ == "__main__":
    main()


