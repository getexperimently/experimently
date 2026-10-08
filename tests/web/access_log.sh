#!/usr/bin/env bash
# tests/web/access_log.sh -- the dashboard image's access log leaves query
# strings out, checked in the BUILT image.
#
#   bash tests/web/access_log.sh [image]     (default experimently-web:core)
#
# Run by the Docker Smoke job (pr-qa-gate.yml) and the Compose Production job
# after they build the dashboard image. It starts one throwaway container with
# no network and no published port, so it cannot collide with a stack on the
# same host, and removes it again.
#
# frontend/nginx.conf is a TEMPLATE: docker-entrypoint.sh renders it with
# envsubst at start-up. A template that reads right can still render wrong
# (an envsubst that expanded every variable would turn `$uri` into an empty
# string), so this reads the RENDERED /etc/nginx/conf.d/default.conf and then
# sends requests and reads what nginx actually wrote.
#
# The requests go to an upstream that is not there (API_UPSTREAM is a closed
# port), so nginx answers 502 for /api/ and still writes the access line.
# Every check runs and reports; the script fails at the end if any of them
# did, so one run shows every property that broke.
#
# What a pass means:
#   - the rendered config still has the `noquery` format with its
#     `$request_method $uri $server_protocol` and the server-level access_log;
#   - each request below has an access line with its method, path and
#     protocol, and no access line carries any of the PROBE values sent in
#     the query strings.
# The error log is NOT checked: when nginx cannot reach the API its error line
# carries the full request line, query included. It is printed for the record.
set -euo pipefail

IMAGE="${1:-experimently-web:core}"
NAME="web-access-log-$$"
PROBES=(PROBETOKEN4711 PROBECODE4712 PROBESTATE4713 PROBENEXT4714)
failures=0

fail() {
    echo "::error::$1"
    failures=$((failures + 1))
}

cleanup() {
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    rm -f rendered.conf access.log error.log base-nginx.conf
}
trap cleanup EXIT

docker run -d --name "$NAME" --network none \
    -e API_UPSTREAM=http://127.0.0.1:1 \
    "$IMAGE" >/dev/null

# Up when /healthz answers (that location has access_log off, so it adds no
# line to what is checked below).
for _ in $(seq 1 30); do
    if docker exec "$NAME" wget -qO /dev/null http://127.0.0.1:8080/healthz 2>/dev/null; then
        break
    fi
    sleep 1
done
docker exec "$NAME" wget -qO /dev/null http://127.0.0.1:8080/healthz

echo "== rendered /etc/nginx/conf.d/default.conf"
docker exec "$NAME" cat /etc/nginx/conf.d/default.conf >rendered.conf
cat rendered.conf
echo "== the base image's log_format main, which noquery copies but for the request line"
docker exec "$NAME" cat /etc/nginx/nginx.conf >base-nginx.conf
grep -A2 'log_format' base-nginx.conf || true

# Fixed strings: the variables must reach nginx exactly as written.
if ! grep -qF "log_format noquery '\$remote_addr - \$remote_user [\$time_local] \"\$request_method \$uri \$server_protocol\" '" rendered.conf; then
    fail "the rendered config has no noquery log_format writing \"\$request_method \$uri \$server_protocol\""
fi
if ! grep -qE '^    access_log /var/log/nginx/access\.log noquery;$' rendered.conf; then
    fail "the rendered config has no server-level 'access_log /var/log/nginx/access.log noquery;'"
fi

# path|query: a results WebSocket opened with ?token=, the OIDC callback, and
# a static page (location / rather than the /api/ proxy).
REQUESTS=(
    "/api/v1/ws/experiments/x/results|token=${PROBES[0]}"
    "/api/v1/auth/sso/oidc/okta/callback|code=${PROBES[1]}&state=${PROBES[2]}"
    "/login|next=${PROBES[3]}"
)
for req in "${REQUESTS[@]}"; do
    # busybox wget exits non-zero on the 502; the access line is what matters.
    docker exec "$NAME" wget -qO /dev/null "http://127.0.0.1:8080${req%%|*}?${req#*|}" >/dev/null 2>&1 || true
done
sleep 1

# access.log is stdout, error.log is stderr (the base image links both).
docker logs "$NAME" >access.log 2>error.log
echo "== access log (stdout)"
cat access.log
echo "== error log (stderr), for the record"
cat error.log

for req in "/api/v1/ws/experiments/x/results" "/api/v1/auth/sso/oidc/okta/callback"; do
    if ! grep -qE "\"GET ${req} HTTP/1\.[01]\" 502 " access.log; then
        fail "no access line \"GET ${req} HTTP/1.x\" 502"
    fi
done
if ! grep -qE '"GET /login(\.html)? HTTP/1\.[01]" 200 ' access.log; then
    fail "no access line \"GET /login HTTP/1.x\" 200"
fi
for probe in "${PROBES[@]}"; do
    if grep -qF "$probe" access.log; then
        fail "the access log carries the query value $probe"
    fi
done

if [ "$failures" -ne 0 ]; then
    echo "access log: $failures check(s) failed"
    exit 1
fi
echo "access log: no query string in any line; method, path and protocol written"
