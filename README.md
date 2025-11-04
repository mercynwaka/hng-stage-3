# hng-stage-3
🧩 Blue-Green Deployment with Automated Failover & Slack Alerts

This project implements a Blue-Green Deployment pattern with a monitoring and alerting system that automatically detects:

High error rates

Pool failovers (e.g. blue → green)

Recovery events

Alerts are sent directly to a configured Slack channel using a webhook integration.

🚀 Project Overview

App Containers: Two Node.js servers (blue and green) behind Nginx reverse proxy

Watcher Service: Monitors /var/log/nginx/access.log for failovers and errors

Slack Integration: Sends real-time notifications for operational events

Chaos Mode: Simulates random upstream failures for testing alert responsiveness

🧱 Folder Structure
hng-stage-3/
├── docker-compose.yml
├── watcher/
│   ├── watcher.py
│   ├── requirements.txt
│--- nginx
│    ├──nginx.template.conf
├── .env
├── runbook.md
└── README.md

⚙️ Setup Instructions
1️⃣ Clone the Repository
git clone <your-repo-url>
cd hng-stage-3

2️⃣ Create .env File
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/XXXXXXXX
ACTIVE_POOL=blue
ERROR_RATE_THRESHOLD=2
WINDOW_SIZE=200
ALERT_COOLDOWN_SEC=300

3️⃣ Start All Services
docker compose up -d --build


This launches:

nginx (reverse proxy)

blue and green app containers

alert_watcher (Python service)

Shared log volume /var/log/nginx

 Chaos Testing Steps
▶️ Enable Chaos Mode

Chaos mode randomly disrupts one pool to simulate service instability:

docker exec -it alert_watcher chaos_mode on

 Trigger Load and Failover

Send multiple requests to simulate normal traffic:

while true; do curl -s http://localhost:8080/ > /dev/null; sleep 0.5; done


When one pool starts failing:

Nginx logs will show upstream 5xx responses.

Watcher detects high error rate → sends alert.

If threshold persists, automatic failover occurs.

🧰 View Active Pool
curl -I http://localhost:8080/


Check the header:

X-App-Pool: blue


After failover:

X-App-Pool: green

📈 Viewing Logs
🔍 Nginx Logs
docker exec -it alert_watcher tail -f /var/log/nginx/access.log


Example line:

pool:blue release:v1-blue upstream_status:200 upstream:172.19.0.3:3000 request_time:0.002

🧾 Watcher Logs
docker logs -f alert_watcher


Look for entries such as:

✅ Slack alert sent: FAILOVER DETECTED
⚠️ High error rate detected: 3.00%

💬 Slack Alerts Verification
✅ Test Alert
docker exec -it alert_watcher python3 -c "import requests, os; requests.post(os.environ['SLACK_WEBHOOK_URL'], json={'text':'✅ Test alert from alert_watcher running on EC2'}).raise_for_status()"


Confirm message appears in Slack channel.

⚠️ Failover Detected

Triggered when blue → green or green → blue.

🚨 High Error Rate Detected

Triggered when 5xx error percentage exceeds ERROR_RATE_THRESHOLD.

♻️ Recovery Message

Sent when error rate drops back to normal range.

🧭 Runbook Reference

See runbook.md
 for:

Alert meanings

Operator actions

Maintenance mode instructions

Acceptance criteria

Full testing checklist

🖼️ Screenshots
<img width="959" height="178" alt="hng3" src="https://github.com/user-attachments/assets/bfdf657f-f9dc-489c-858e-4e1996b36a33" />
<img width="398" height="304" alt="hng2" src="https://github.com/user-attachments/assets/a03e9156-e77e-4869-a548-da5ba38620ea" />

<img width="465" height="296" alt="hng4" src="https://github.com/user-attachments/assets/3dcf419c-d110-475e-b5eb-38286c056db3" />
<img width="487" height="282" alt="hng5" src="https://github.com/user-attachments/assets/552ac0f9-0614-4e2a-92f0-e18aab210abe" />
<img width="354" height="285" alt="hng7" src="https://github.com/user-attachments/assets/38610f2c-86fe-46c2-924a-489c0e8eae6d" />


🧾 Notes

Use docker compose down && docker compose up -d --build to restart cleanly.

To suppress alerts during updates:

docker exec -it alert_watcher touch /watcher/data/maintenance_mode


Remove the file after maintenance:

docker exec -it alert_watcher rm /watcher/data/maintenance_mode


System auto-recovers after failover and resumes normal monitoring.
