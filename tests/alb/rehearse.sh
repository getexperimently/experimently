#!/usr/bin/env bash
# tests/alb/rehearse.sh -- assertions against the ALB-shaped compose stack.
#
# Run by the Docker Smoke job after
#   docker compose -f docker-compose.yml -f tests/alb/docker-compose.alb.yml up ...
# and runnable by hand against the same stack. Every request goes to the `alb`
# service with the public hostname as Host, the way a browser reaches
# https://app.<domain> in AWS.
#
#   ALB_URL      the alb service                 (default http://localhost:8090)
#   WEB_URL      the dashboard container itself  (default http://localhost:3000)
#   PUBLIC_HOST  the host PUBLIC_BASE_URL names  (default app.example.test)
#   ADMIN_EMAIL / ADMIN_PASSWORD  the seeded demo admin (docker-compose.yml's
#                FIRST_SUPERUSER defaults)
#
# Responses go to files, never into a pipe: `curl | grep -q` makes curl exit
# 23 (SIGPIPE) on a large page, and a pipe hides curl's own status.
set -euo pipefail

ALB_URL="${ALB_URL:-http://localhost:8090}"
WEB_URL="${WEB_URL:-http://localhost:3000}"
PUBLIC_HOST="${PUBLIC_HOST:-app.example.test}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@demo.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-Demo1234!}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fail() {
    echo "::error::$*"
    echo "$*" >&2
    exit 1
}

# status <out-file> <curl args...>: the HTTP status, the body in <out-file>.
status() {
    local out="$1"
    shift
    curl -s -o "$out" -w '%{http_code}' --max-time 20 "$@" || true
}

# 1. The readiness probe answers through the ALB. Probes are exempt from the
#    Host check, so this is green whatever PUBLIC_BASE_URL says -- which is why
#    it proves nothing on its own and every check after it hits a non-probe path.
code="$(status "$work/ready.json" -H "Host: $PUBLIC_HOST" "$ALB_URL/health/ready")"
test "$code" = "200" || fail "expected 200 from /health/ready, got $code"
grep -q '"status":"healthy"' "$work/ready.json" || fail "/health/ready is not healthy: $(cat "$work/ready.json")"
echo "ok  /health/ready through the alb: 200 healthy"

# 2. A NON-probe API path, public Host, no credentials: the Host check admits
#    it and the auth gate refuses it. A 400 here is the Host check refusing the
#    dashboard's own hostname -- the dashboard would be dead while every probe
#    stays green. The trailing slash avoids the 307 to it.
code="$(status "$work/experiments.json" -H "Host: $PUBLIC_HOST" "$ALB_URL/api/v1/experiments/")"
test "$code" = "401" || fail "expected 401 without credentials, got $code"
echo "ok  /api/v1/experiments/ with Host: $PUBLIC_HOST: 401"

# 3. The Host check is actually ON. Without this the 401 above would also pass
#    with PUBLIC_BASE_URL unset (check off, the development default), which is
#    how Docker Smoke's own 401 passes.
code="$(status "$work/foreign.json" -H "Host: not-$PUBLIC_HOST" "$ALB_URL/api/v1/experiments/")"
test "$code" = "400" || fail "expected 400 for a Host the API does not serve, got $code: the Host check is off"
echo "ok  /api/v1/experiments/ with Host: not-$PUBLIC_HOST: 400 (Host check on)"

# 4. The dashboard's nginx does not proxy /api (API_UPSTREAM is unreachable, as
#    in AWS), so check 2 cannot have been answered through it.
code="$(status "$work/web-api.txt" "$WEB_URL/api/v1/experiments/")"
test "$code" = "502" || fail "expected 502 from the dashboard container's /api (it must not proxy), got $code"
echo "ok  the dashboard container does not proxy /api: 502"

# 5. The default action serves the dashboard: the static export's HTML, with
#    the dashboard nginx's CSP.
code="$(status "$work/index.html" -D "$work/index.headers" -H "Host: $PUBLIC_HOST" "$ALB_URL/")"
test "$code" = "200" || fail "expected 200 from / (the dashboard), got $code"
grep -qi '^content-type: text/html' "$work/index.headers" || fail "/ is not HTML: $(grep -i '^content-type' "$work/index.headers" || echo 'no content-type')"
grep -q '/_next/static/' "$work/index.html" || fail "/ is not the dashboard's static export (no /_next/static/ asset)"
echo "ok  / through the alb: the dashboard HTML"

# 6. connect-src permits 'self': the dashboard calls /api on its own origin,
#    and a connect-src without 'self' breaks every call in the browser while
#    curl sees nothing wrong.
csp="$(tr -d '\r' <"$work/index.headers" | grep -i '^content-security-policy:' || true)"
test -n "$csp" || fail "/ carries no Content-Security-Policy"
connect_src="$(printf '%s\n' "${csp#*:}" | tr ';' '\n' | sed 's/^ *//' | grep -i '^connect-src ' || true)"
printf '%s\n' "$connect_src" | grep -qE "(^| )'self'( |$)" \
    || fail "the CSP connect-src does not permit 'self': ${connect_src:-no connect-src directive}"
echo "ok  CSP $connect_src"

# 7. A login and one authenticated non-probe call, through the alb.
code="$(status "$work/login.json" -X POST -H "Host: $PUBLIC_HOST" \
    -H 'content-type: application/json' \
    -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}" \
    "$ALB_URL/api/v1/auth/login")"
test "$code" = "200" || fail "expected 200 from the login through the alb, got $code: $(cat "$work/login.json")"
token="$(jq -er .access_token "$work/login.json")" || fail "the login answered 200 with no access_token"
code="$(status "$work/list.json" -H "Host: $PUBLIC_HOST" -H "Authorization: Bearer $token" \
    "$ALB_URL/api/v1/experiments/")"
test "$code" = "200" || fail "expected 200 from an authenticated /api/v1/experiments/, got $code"
echo "ok  login + authenticated /api/v1/experiments/ through the alb: 200"

echo "ALB topology rehearsal: all checks passed"
