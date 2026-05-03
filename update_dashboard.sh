#!/bin/bash
# update_dashboard.sh
# Pushes grafana/dashboards/strava.json to Grafana via API.
# Run this after editing the JSON file instead of restarting the container.

GRAFANA_URL="http://localhost:3001"
GRAFANA_USER="admin"
GRAFANA_PASS="admin"
DASHBOARD_JSON="$(dirname "$0")/grafana/dashboards/strava.json"

# Wrap the dashboard JSON in the API payload format
PAYLOAD=$(python3 - <<EOF
import json

with open("$DASHBOARD_JSON") as f:
    dashboard = json.load(f)

payload = {
    "dashboard": dashboard,
    "overwrite": True,
    "folderId": 0
}
print(json.dumps(payload))
EOF
)

RESPONSE=$(curl -s -X POST "$GRAFANA_URL/api/dashboards/db" \
  -u "$GRAFANA_USER:$GRAFANA_PASS" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

STATUS=$(echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','error'))")

if [ "$STATUS" = "success" ]; then
  echo "✅ Dashboard updated successfully."
else
  echo "❌ Failed: $RESPONSE"
fi
