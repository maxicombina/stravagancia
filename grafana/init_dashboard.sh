#!/bin/sh
# Waits for Grafana to be ready, then provisions the Strava dashboard via API.

GRAFANA_URL="http://localhost:3001"
DASHBOARD_FILE="$(dirname "$0")/dashboards/strava.json"

echo "Waiting for Grafana..."
until curl -sf "$GRAFANA_URL/api/health" > /dev/null; do sleep 2; done
echo "Grafana is up."

# Create/update dashboard from exported JSON
PAYLOAD=$(python3 -c "
import json, sys
d = json.load(open('$DASHBOARD_FILE'))
print(json.dumps({'overwrite': True, 'folderId': 0, 'dashboard': d}))
")

curl -sf -u admin:admin -X POST "$GRAFANA_URL/api/dashboards/db" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" && echo "Dashboard provisioned." || echo "Dashboard failed."
