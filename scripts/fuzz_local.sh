#!/usr/bin/env bash
# One API fuzzing pass on this machine, the way fuzz.yml runs it in CI:
#
#   make fuzz FUZZ_SEED=<seed> SHA=<commit> PASS=<superuser|viewer|sdk>
#
# A public run prints counts only; this is where the failing operations are
# looked at. It
#
#   * refuses unless SHA is the commit checked out (HEAD) and the tree is
#     clean -- it never checks anything out itself, so the stack under test is
#     built from exactly that commit;
#   * builds and starts the API with Postgres and Redis as its own compose
#     project, experimently-fuzz, on its own ports (API 18700) and its own
#     image tag (experimently-api:fuzz), with the full profile and the data
#     seed set here (SEED=demo, plus sdk-contract for the sdk pass) -- never
#     the make variable -- and with tests/fuzz/compose.fuzz.yml pointing every
#     AWS call at a closed local port;
#   * runs Schemathesis with the workflow's flags (the same filters, from
#     scripts/fuzz_check.py) in a new temporary directory outside the tree,
#     which holds its report, its output and the operations behind each count
#     (details.json), and prints that directory's path;
#   * removes the compose project and its volumes on the way out, whatever
#     the result, and exits with the pass's verdict (0 green, 1 red).
#
# The API key and bearer token are read into variables and never printed.
set -euo pipefail

usage="usage: make fuzz FUZZ_SEED=<seed> SHA=<commit> PASS=<superuser|viewer|sdk>"
fuzz_seed=${1-}
sha=${2-}
pass=${3-}

refuse() {
  echo "make fuzz: $1" >&2
  echo "$usage" >&2
  exit 2
}

case "$pass" in
  superuser | viewer | sdk) ;;
  *) refuse "PASS must be superuser, viewer or sdk" ;;
esac
[[ "$fuzz_seed" =~ ^(0|[1-9][0-9]{0,9})$ ]] ||
  refuse "FUZZ_SEED must be an integer of one to ten digits"
[ -n "$sha" ] || refuse "SHA must name the commit to fuzz"

root=$(git rev-parse --show-toplevel 2> /dev/null) ||
  refuse "this is not a git checkout"
cd "$root"
head=$(git rev-parse HEAD)
wanted=$(git rev-parse --verify --quiet "${sha}^{commit}") ||
  refuse "SHA $sha is not a commit of this repository"
[ "$wanted" = "$head" ] ||
  refuse "SHA $sha is not HEAD ($head); check that commit out first (make fuzz checks nothing out)"
[ -z "$(git status --porcelain)" ] ||
  refuse "the tree has changes or untracked files; commit or stash them first"

python=${FUZZ_PYTHON:-python3}
"$python" -c 'import sys; sys.exit(sys.version_info < (3, 11))' ||
  refuse "needs Python 3.11 or newer as python3 (or FUZZ_PYTHON)"

project=experimently-fuzz
api=http://127.0.0.1:18700
compose=(docker compose -p "$project" --env-file /dev/null
  -f docker-compose.yml -f tests/fuzz/compose.fuzz.yml)
# Every variable docker-compose.yml interpolates that matters here is set
# explicitly, so neither the developer's shell nor a make variable on the
# command line (SEED above all) reaches the stack.
export EXPERIMENTLY_PROFILE=full EXPERIMENTLY_IMAGE_TAG=fuzz
export API_HOST_PORT=18700 POSTGRES_HOST_PORT=18701 REDIS_HOST_PORT=18702 FRONTEND_HOST_PORT=18703
if [ "$pass" = sdk ]; then
  export SEED=demo,sdk-contract
else
  export SEED=demo
fi

work=$(mktemp -d "${TMPDIR:-/tmp}/experimently-fuzz.XXXXXX")
cleanup() {
  if ! "${compose[@]}" down -v --remove-orphans > "$work/compose-down.log" 2>&1; then
    echo "make fuzz: could not remove the $project project; run: docker compose -p $project down -v" >&2
  fi
}
trap cleanup EXIT

echo "make fuzz: building and starting the $project stack (logs in $work)"
"${compose[@]}" up -d --build --wait api > "$work/compose-up.log" 2>&1 || {
  echo "make fuzz: the stack did not start; see $work/compose-up.log" >&2
  exit 1
}
# The same refusal as the workflow's: nothing may reach AWS.
[ "$("${compose[@]}" exec -T api printenv AWS_ENDPOINT_URL)" = "http://127.0.0.1:9" ] || {
  echo "make fuzz: the api container does not have AWS_ENDPOINT_URL=http://127.0.0.1:9" >&2
  exit 1
}

"$python" -m venv "$work/venv"
"$work/venv/bin/pip" install --quiet --disable-pip-version-check \
  -r tests/fuzz/requirements.txt > "$work/pip.log" 2>&1 || {
  echo "make fuzz: could not install tests/fuzz/requirements.txt; see $work/pip.log" >&2
  exit 1
}

if [ "$pass" = sdk ]; then
  key=$("${compose[@]}" exec -T api cat /data/demo/sdk-contract/.api_key)
  auth=(-H "X-API-Key: $key")
else
  case "$pass" in
    superuser) email=admin@demo.com ;;
    viewer) email=viewer@demo.com ;;
  esac
  token=$(curl -sf -X POST "$api/api/v1/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"email\": \"$email\", \"password\": \"Demo1234!\"}" |
    "$python" -c 'import json, sys; print(json.load(sys.stdin)["access_token"])') || {
    echo "make fuzz: could not sign in as $email" >&2
    exit 1
  }
  auth=(-H "Authorization: Bearer $token")
fi

curl -sf "$api/api/v1/openapi.json" -o "$work/openapi.json"
"$python" scripts/fuzz_check.py args --pass "$pass" --schema "$work/openapi.json" > "$work/filters.txt"
filters=()
while IFS= read -r arg; do filters+=("$arg"); done < "$work/filters.txt"

echo "make fuzz: fuzzing the $pass pass (seed $fuzz_seed); this takes a while"
set +e
(
  cd "$work" &&
    "$work/venv/bin/schemathesis" run "$api/api/v1/openapi.json" \
      --checks not_a_server_error --phases examples,coverage,fuzzing \
      --max-examples 5 --workers 1 --rate-limit 4/s \
      --seed "$fuzz_seed" --generation-deterministic \
      --report ndjson --report-dir "$work/report" \
      "${filters[@]}" "${auth[@]}"
) > "$work/schemathesis.out" 2>&1
set -e

verdict=0
"$python" scripts/fuzz_check.py evaluate --pass "$pass" \
  --schema "$work/openapi.json" --report-dir "$work/report" \
  --seed "$fuzz_seed" --sha "$head" --details "$work/details.json" || verdict=$?
echo "make fuzz: the reproduction directory is $work"
exit "$verdict"
