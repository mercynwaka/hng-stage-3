Alert Watcher Runbook

📘 Overview

This runbook explains the alert system used in the Blue-Green Deployment setup for hng-stage-3.
The watcher service monitors Nginx access logs for failover events and error-rate anomalies, and sends alerts to Slack via webhook.

⚙️ Configuration

Variable	                           Description	                   Default/Example
SLACK_WEBHOOK_URL	        Slack Incoming Webhook URL	                 (set in .env)
ACTIVE_POOL	                Initial active pool	                              blue
ERROR_RATE_THRESHOLD	  Error rate percentage that triggers alert	            2
WINDOW_SIZE	               Number of recent requests to analyze              	200
ALERT_COOLDOWN_SEC	       Minimum seconds between repeated alerts	            300
MAINTENANCE_FILE	   File path that suppresses alerts when present	   /watcher/data/maintenance_mode



Log Source: /var/log/nginx/access.log

Each log line includes structured fields:
pool:blue release:v1-blue upstream_status:200 upstream:172.19.0.3:3000


🚨 Alert Types and Operator Actions
1️⃣ Failover Detected

Trigger:
Watcher detects a change in active pool (blue → green or vice versa).

Slack Message Example:

🚨 Failover Detected!
Pool changed from blue → green

Operator Action:

Verify health of the primary pool container (blue).

Check service logs for crash or 5xx spikes.

Confirm that backup pool (green) is serving requests correctly.

Investigate root cause before toggling back.



2️⃣ High Error Rate Detected

Trigger:
5xx errors exceed the defined threshold (e.g., > 2%) over the last 200 requests.

Slack Message Example:

⚠️ High Error Rate Detected!
Error Rate: 3.00% 5xx responses over last 200 requests

Operator Action:

Inspect Nginx and app logs for recurring 5xx errors.

Identify failing upstream or service component.

If persistent, consider toggling traffic to the standby pool.

Keep monitoring until error rate returns below threshold.




3️⃣ Error Rate Recovered

Trigger:
Error rate falls below threshold after a previous breach.

Slack Message Example:

✅ Error rate recovered: 0.5% 5xx responses over last 200 requests

Operator Action:

Confirm service stability has returned.

Document incident duration and resolution summary.


4️⃣ Maintenance Mode

Trigger:
Presence of the maintenance mode flag file (/watcher/data/maintenance_mode).
Alerts are automatically suppressed until this file is removed.

Slack Message Example:

🛠️ Maintenance mode ENABLED — alerts suppressed

Operator Action:

Use this before planned pool toggles or deployments.

Remove the file (rm /watcher/data/maintenance_mode) to resume alerting.



docker logs -f alert_watcher
Confirm Slack delivery and formatting



Operational Notes

Alerts are rate-limited (5-minute cooldown per alert type).

The watcher runs independently — no modification to app containers.

The system relies only on logs, not on HTTP request routing.

To verify Slack integration:
docker exec -it alert_watcher python3 -c "import requests, os; requests.post(os.environ['SLACK_WEBHOOK_URL'], json={'text':'✅ Test alert from alert_watcher'}).raise_for_status()"

To enable maintenance mode:
docker exec -it alert_watcher touch /watcher/data/maintenance_mode

To disable maintenance mode:
docker exec -it alert_watcher rm /watcher/data/maintenance_mode





