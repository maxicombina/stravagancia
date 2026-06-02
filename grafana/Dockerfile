# Grafana for Render (free tier, no persistent disk).
# Everything is provisioned from files baked into the image, so each boot
# rebuilds the datasource, dashboard and admin password deterministically.
FROM grafana/grafana:11.5.0

# Datasource (Neon) + dashboard provider config -> /etc/grafana/provisioning
COPY provisioning /etc/grafana/provisioning

# Dashboard JSON loaded by the provider (see provisioning/dashboards/dashboards.yml)
COPY dashboards /var/lib/grafana/dashboards

# Non-secret config baked in. Secrets/host-specific values are set as env vars
# on Render: GF_SECURITY_ADMIN_PASSWORD, NEON_PASSWORD, GF_SERVER_ROOT_URL.
ENV GF_AUTH_ANONYMOUS_ENABLED=true \
    GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer \
    GF_AUTH_DISABLE_LOGIN_FORM=false \
    GF_SECURITY_ALLOW_EMBEDDING=true \
    GF_FEATURE_TOGGLES_ENABLE=publicDashboards \
    GF_USERS_DEFAULT_THEME=light \
    GF_SERVER_HTTP_PORT=10000 \
    GF_DATE_FORMATS_INTERVAL_MINUTE="HH:mm" \
    GF_DATE_FORMATS_INTERVAL_HOUR="DD/MM HH:mm" \
    GF_DATE_FORMATS_INTERVAL_DAY="DD/MM" \
    GF_DATE_FORMATS_INTERVAL_MONTH="MM/YYYY" \
    GF_DATE_FORMATS_INTERVAL_YEAR="YYYY"

# Render routes to the port in $PORT (default 10000); Grafana listens there.
EXPOSE 10000
