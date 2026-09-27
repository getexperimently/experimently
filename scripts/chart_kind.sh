#!/usr/bin/env bash
# The chart-kind job (.github/workflows/chart-kind.yml): the Helm chart
# installed on a kind cluster, behind ingress-nginx, from this pull request's
# own images, by the blocks of docs/self-hosting/kubernetes.md.
#
# One phase per subcommand, run in this order by the workflow:
#
#   cluster    kind cluster with ports 80/443 on the host, and ingress-nginx
#              from a manifest pinned by sha256
#   load       the PR's images, tagged as the chart's defaults, loaded into kind
#   dry-run    the rendered chart accepted by the real API server (and its
#              admission webhooks); an IP-literal or host:port Ingress host
#              refused by it -- the refusal the chart's schema mirrors
#   guide      the guide's blocks, extracted from the page (scripts/guide_blocks.py):
#                secrets twice (the second fails AlreadyExists, the Secret's
#                  resourceVersion unchanged), install, the pods run the PR's
#                  images, a request through the Ingress answers 401 (400 is
#                  the Host check refusing publicBaseUrl's host), first admin,
#                  helm test, migrations ran once, upgrade, no restarts
#   replicas   a fresh install with api.replicaCount=2: exactly one bootstrap
#              says "(created)", the other "(upgraded)", no restarts
#   summary    the per-phase timings (also to $GITHUB_STEP_SUMMARY)
#   diagnose   pods, events and API logs, for a failed run
#   teardown   delete the cluster
#
# Inputs (environment): PROFILE (core|full); API_IMAGE and WEB_IMAGE, the local
# images to load; INGRESS_NGINX_MANIFEST_URL and INGRESS_NGINX_MANIFEST_SHA256;
# KIND_NODE_IMAGE; optional KIND_CLUSTER, KIND_HOST (must resolve to
# 127.0.0.1), CHART_KIND_WORK.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT=$(pwd)

PROFILE=${PROFILE:?PROFILE must be core or full}
CLUSTER=${KIND_CLUSTER:-chart-kind}
HOST=${KIND_HOST:-experimently.kind.test}
WORK=${CHART_KIND_WORK:-${RUNNER_TEMP:-/tmp}/chart-kind-$PROFILE}
GUIDE=docs/self-hosting/kubernetes.md
GUIDE_BLOCKS=secrets,install,first-admin,upgrade
CHART_DIR=charts/experimently
# The guide's own names: its blocks hard-code them.
NS=experimently
RELEASE=experimently
SECRET=experimently-secrets
ADMIN=admin@example.com
DRY_RUN_NS=chart-kind-dry-run
API_REPO=ghcr.io/getexperimently/experimently
WEB_REPO=ghcr.io/getexperimently/experimently-web

mkdir -p "$WORK"
TIMINGS="$WORK/timings.tsv"

say() { printf '[chart-kind] %s\n' "$*"; }
fail() {
    printf '::error::%s\n' "$*"
    exit 1
}

# phase NAME COMMAND...: run a phase and record how long it took.
phase() {
    local name=$1 start end
    shift
    start=$(date +%s)
    say "== $name"
    "$@"
    end=$(date +%s)
    printf '%s\t%s\n' "$name" "$((end - start))" >>"$TIMINGS"
    say "== $name: $((end - start))s"
}

app_version() {
    sed -n 's/^appVersion: "\([^"]*\)".*/\1/p' "$CHART_DIR/Chart.yaml"
}

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | cut -d' ' -f1
    else
        shasum -a 256 "$1" | cut -d' ' -f1
    fi
}

# ---------------------------------------------------------------------------
do_cluster() {
    : "${KIND_NODE_IMAGE:?}" "${INGRESS_NGINX_MANIFEST_URL:?}" "${INGRESS_NGINX_MANIFEST_SHA256:?}"
    cat >"$WORK/kind.yaml" <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    image: $KIND_NODE_IMAGE
    kubeadmConfigPatches:
      - |
        kind: InitConfiguration
        nodeRegistration:
          kubeletExtraArgs:
            node-labels: "ingress-ready=true"
    extraPortMappings:
      - containerPort: 80
        hostPort: 80
        protocol: TCP
      - containerPort: 443
        hostPort: 443
        protocol: TCP
EOF
    kind create cluster --name "$CLUSTER" --config "$WORK/kind.yaml" --wait 180s
    kubectl get nodes -o wide

    curl -fsSL -o "$WORK/ingress-nginx.yaml" "$INGRESS_NGINX_MANIFEST_URL"
    local got
    got=$(sha256_of "$WORK/ingress-nginx.yaml")
    [ "$got" = "$INGRESS_NGINX_MANIFEST_SHA256" ] ||
        fail "ingress-nginx manifest sha256 $got, pinned $INGRESS_NGINX_MANIFEST_SHA256"
    kubectl apply -f "$WORK/ingress-nginx.yaml"
    kubectl wait --namespace ingress-nginx --for=condition=ready pod \
        --selector=app.kubernetes.io/component=controller --timeout=300s
}

# ---------------------------------------------------------------------------
do_load() {
    : "${API_IMAGE:?}" "${WEB_IMAGE:?}"
    local tag
    tag="$PROFILE-$(app_version)"
    # The chart's default references, so the guide's install command needs no
    # image override. pullPolicy IfNotPresent then uses these; the guide phase
    # asserts the running pods are these images, not a registry's.
    docker tag "$API_IMAGE" "$API_REPO:$tag"
    docker tag "$WEB_IMAGE" "$WEB_REPO:$tag"
    kind load docker-image --name "$CLUSTER" "$API_REPO:$tag" "$WEB_REPO:$tag"
    {
        echo "api=$(docker image inspect --format '{{.Id}}' "$API_REPO:$tag")"
        echo "web=$(docker image inspect --format '{{.Id}}' "$WEB_REPO:$tag")"
    } >"$WORK/images.txt"
    cat "$WORK/images.txt"
}

# ---------------------------------------------------------------------------
# kubectl apply --dry-run=server, retried while ingress-nginx's admission
# webhook is not answering yet (it becomes Ready before its endpoint does).
server_dry_run() {
    local file=$1 out=$2 attempt
    for attempt in $(seq 1 30); do
        if kubectl apply --dry-run=server -n "$DRY_RUN_NS" -f "$file" >"$out" 2>&1; then
            return 0
        fi
        if grep -q 'failed calling webhook' "$out"; then
            sleep 2
            continue
        fi
        return 1
    done
    return 1
}

do_dry_run() {
    local values
    # A Pod is admitted only if its ServiceAccount exists, so that one object
    # is created for real, in a namespace of its own.
    kubectl create namespace "$DRY_RUN_NS"
    helm template exp "$CHART_DIR" -f "$CHART_DIR/ci/values-core.yaml" \
        --show-only templates/serviceaccount.yaml | kubectl apply -n "$DRY_RUN_NS" -f -
    for values in "$CHART_DIR/ci/values-core.yaml" "$CHART_DIR/ci/values-full.yaml"; do
        helm template exp "$CHART_DIR" -f "$values" >"$WORK/render.yaml"
        server_dry_run "$WORK/render.yaml" "$WORK/dry-run.log" ||
            { cat "$WORK/dry-run.log"; fail "the API server refused the chart rendered with $values"; }
        say "$values: accepted by the API server ($(grep -c 'server dry run' "$WORK/dry-run.log") objects)"
    done

    # The chart refuses these publicBaseUrl hosts before Kubernetes sees them;
    # this is the evidence that Kubernetes would refuse them too.
    helm template exp "$CHART_DIR" -f "$CHART_DIR/ci/values-core.yaml" \
        --show-only templates/ingress.yaml >"$WORK/ingress.yaml"
    local bad expect
    for bad in '10.0.0.5|must be a DNS name, not an IP address' \
        'experimently.example.com:8080|a lowercase RFC 1123 subdomain'; do
        expect=${bad#*|}
        bad=${bad%%|*}
        sed "s/host: \"experimently.example.com\"/host: \"$bad\"/" "$WORK/ingress.yaml" >"$WORK/bad-ingress.yaml"
        grep -qF "host: \"$bad\"" "$WORK/bad-ingress.yaml" ||
            fail "could not plant host $bad in the rendered Ingress"
        if server_dry_run "$WORK/bad-ingress.yaml" "$WORK/bad.log"; then
            fail "the API server accepted an Ingress host of $bad"
        fi
        grep -qF "$expect" "$WORK/bad.log" || { cat "$WORK/bad.log"; fail "host $bad refused, but not for: $expect"; }
        say "Ingress host $bad: refused by the API server ($expect)"
    done
    kubectl delete namespace "$DRY_RUN_NS" --wait=false
}

# ---------------------------------------------------------------------------
# run_block NAME: one of the guide's blocks, as a reader runs it, in a shell
# with the guide's four variables. stdout and stderr go to $WORK/NAME.{out,err}.
run_block() {
    local name=$1 status=0
    say "--- guide block '$name':"
    sed 's/^/    | /' "$WORK/blocks/$name.sh"
    CHART="$REPO_ROOT/$CHART_DIR" PUBLIC_BASE_URL="http://$HOST" ADMIN_EMAIL="$ADMIN" PROFILE="$PROFILE" \
        bash -euo pipefail "$WORK/blocks/$name.sh" >"$WORK/$name.out" 2>"$WORK/$name.err" || status=$?
    sed 's/^/    out: /' "$WORK/$name.out"
    sed 's/^/    err: /' "$WORK/$name.err"
    say "--- '$name' exited $status"
    return "$status"
}

# The pods running our images run exactly the images this job loaded.
assert_images() {
    local ns=$1 api web ids
    api=$(sed -n 's/^api=//p' "$WORK/images.txt")
    web=$(sed -n 's/^web=//p' "$WORK/images.txt")
    ids=$(kubectl get pods -n "$ns" -l "app.kubernetes.io/component in (api,web)" \
        -o jsonpath='{range .items[*]}{range .status.initContainerStatuses[*]}{.image}{" "}{.imageID}{"\n"}{end}{range .status.containerStatuses[*]}{.image}{" "}{.imageID}{"\n"}{end}{end}')
    printf '%s\n' "$ids"
    [ -n "$ids" ] || fail "no api or web containers in $ns"
    local image id want
    while read -r image id; do
        [ -n "$image" ] || continue
        case "$image" in
            *experimently-web:*) want=$web ;;
            *experimently:*) want=$api ;;
            *) fail "unexpected image $image in $ns" ;;
        esac
        [ "$id" = "$want" ] ||
            fail "$image runs $id, not the image this job built ($want)"
    done <<<"$ids"
    say "$ns: every api/web container runs this job's images"
}

# assert_migrations NS RELEASE PODS CREATED UPGRADED: the bootstrap ran once
# per pod, in its `migrate` init container, never in the `api` container.
assert_migrations() {
    local ns=$1 release=$2 want_pods=$3 want_created=$4 want_upgraded=$5
    local pods pod n=0 created=0 upgraded=0 in_api=0 not_skipped=0 c
    pods=$(kubectl get pods -n "$ns" \
        -l "app.kubernetes.io/component=api,app.kubernetes.io/instance=$release" \
        -o jsonpath='{.items[*].metadata.name}')
    for pod in $pods; do
        n=$((n + 1))
        # A bootstrap that failed and was retried leaves only the retry's log
        # behind, so the counts below cannot see it; its restart can.
        c=$(kubectl get pod -n "$ns" "$pod" \
            -o jsonpath='{.status.initContainerStatuses[?(@.name=="migrate")].restartCount}')
        if [ "${c:-0}" -ne 0 ]; then
            kubectl logs -n "$ns" "$pod" -c migrate --previous --tail=40 || true
            fail "$pod: the migrate container restarted $c time(s): a bootstrap failed and was retried"
        fi
        kubectl logs -n "$ns" "$pod" -c migrate >"$WORK/$pod.migrate.log"
        kubectl logs -n "$ns" "$pod" -c api >"$WORK/$pod.api.log"
        c=$(grep -c 'Database bootstrap complete (created)' "$WORK/$pod.migrate.log" || true)
        created=$((created + c))
        c=$(grep -c 'Database bootstrap complete (upgraded)' "$WORK/$pod.migrate.log" || true)
        upgraded=$((upgraded + c))
        c=$(grep -c 'Database bootstrap complete' "$WORK/$pod.api.log" || true)
        in_api=$((in_api + c))
        grep 'Database bootstrap complete\|skipping bootstrap' "$WORK/$pod.migrate.log" "$WORK/$pod.api.log" || true
        grep -qF 'RUN_MIGRATIONS=false: skipping bootstrap' "$WORK/$pod.api.log" ||
            not_skipped=$((not_skipped + 1))
    done
    say "$ns: $n api pods; migrate: $created created, $upgraded upgraded; api container: $in_api"
    [ "$n" -eq "$want_pods" ] || fail "$ns: $n api pods, expected $want_pods"
    [ "$in_api" -eq 0 ] || fail "$ns: the bootstrap ran in the api container $in_api time(s); migrations must run only in migrate"
    [ "$not_skipped" -eq 0 ] || fail "$ns: $not_skipped api container(s) did not log that they skipped the bootstrap"
    [ "$created" -eq "$want_created" ] || fail "$ns: $created bootstraps said (created), expected exactly $want_created"
    [ "$upgraded" -eq "$want_upgraded" ] || fail "$ns: $upgraded bootstraps said (upgraded), expected $want_upgraded"
}

assert_no_restarts() {
    local ns=$1 restarts
    kubectl get pods -n "$ns" -o wide
    restarts=$(kubectl get pods -n "$ns" \
        -o jsonpath='{range .items[*]}{range .status.initContainerStatuses[*]}{.restartCount}{"\n"}{end}{range .status.containerStatuses[*]}{.restartCount}{"\n"}{end}{end}' |
        awk '{s += $1} END {print s + 0}')
    [ "$restarts" -eq 0 ] || fail "$ns: $restarts container restart(s)"
    say "$ns: 0 restarts"
}

secret_state() {
    kubectl get secret "$SECRET" -n "$NS" -o jsonpath='{.metadata.resourceVersion} {.data}' | sha256_of /dev/stdin
}

do_guide() {
    python3 scripts/guide_blocks.py "$GUIDE" --expect "$GUIDE_BLOCKS" --out "$WORK/blocks"

    run_block secrets || fail "the guide's secrets block failed"
    local rv before after
    rv=$(kubectl get secret "$SECRET" -n "$NS" -o jsonpath='{.metadata.resourceVersion}')
    before=$(secret_state)
    if run_block secrets; then
        fail "the guide's secrets block succeeded a second time: it must create, never replace"
    fi
    grep -qF "secrets \"$SECRET\" already exists" "$WORK/secrets.err" ||
        fail "the second secrets run failed, but not with AlreadyExists"
    after=$(secret_state)
    [ "$before" = "$after" ] || fail "the second secrets run changed the Secret"
    say "secrets block run twice: AlreadyExists, resourceVersion $rv unchanged"

    run_block install || fail "the guide's install block failed"
    assert_images "$NS"

    # `helm install --wait` returns when the pods are Ready; ingress-nginx
    # picks up their endpoints a few seconds later and answers 503 until then.
    # Only "not routed yet" is waited out -- never a 400 or a 401.
    local code attempt
    for attempt in $(seq 1 45); do
        code=$(curl -s -o "$WORK/ingress.body" -w '%{http_code}' "http://$HOST/api/v1/experiments/")
        case "$code" in
            404 | 502 | 503 | 504) sleep 2 ;;
            *) break ;;
        esac
    done
    say "through the Ingress after $attempt attempt(s)"
    case "$code" in
        401) say "through the Ingress, http://$HOST/api/v1/experiments/: 401" ;;
        400)
            cat "$WORK/ingress.body"; echo
            fail "through the Ingress the API refused the Host (400): its ALLOWED_HOSTS does not include $HOST, publicBaseUrl's host"
            ;;
        *)
            cat "$WORK/ingress.body"; echo
            fail "through the Ingress, http://$HOST/api/v1/experiments/: $code, expected 401"
            ;;
    esac
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://$HOST/")
    [ "$code" = 200 ] || fail "through the Ingress, the dashboard http://$HOST/: $code, expected 200"
    say "through the Ingress, the dashboard http://$HOST/: 200"

    run_block first-admin || fail "the guide's first-admin block failed"
    [ "$(cat "$WORK/first-admin.out")" = $'401\nADMIN' ] ||
        fail "the first-admin block printed something other than 401 then ADMIN"

    helm test "$RELEASE" -n "$NS" --logs
    assert_migrations "$NS" "$RELEASE" 1 1 0

    run_block upgrade || fail "the guide's upgrade block failed"
    local revision
    revision=$(helm history "$RELEASE" -n "$NS" --max 1 -o json | python3 -c 'import json,sys; r=json.load(sys.stdin)[-1]; print(r["revision"], r["status"])')
    [ "$revision" = "2 deployed" ] || fail "after the upgrade block: revision/status $revision, expected 2 deployed"
    say "upgrade: revision 2 deployed"
    assert_migrations "$NS" "$RELEASE" 1 1 0
    assert_no_restarts "$NS"

    # Free the node for the next phase.
    helm uninstall "$RELEASE" -n "$NS" --wait
    kubectl delete namespace "$NS" --wait=true
}

# ---------------------------------------------------------------------------
do_replicas() {
    local ns=chart-kind-replicas release=r2
    kubectl create namespace "$ns"
    helm install "$release" "$CHART_DIR" -n "$ns" \
        --set profile="$PROFILE" \
        --set publicBaseUrl="http://replicas.$HOST" \
        --set firstSuperuser="$ADMIN" \
        --set ingress.enabled=false \
        --set api.replicaCount=2 \
        --set secrets.secretKey="$(openssl rand -hex 32)" \
        --set secrets.firstSuperuserPassword="$(openssl rand -hex 16)" \
        --set secrets.postgresUser=experimently \
        --set secrets.postgresPassword="$(openssl rand -hex 32)" \
        --set secrets.auditHmacKey="$(openssl rand -hex 32)" \
        --wait --timeout 10m
    assert_images "$ns"
    assert_migrations "$ns" "$release" 2 1 1
    assert_no_restarts "$ns"
}

# ---------------------------------------------------------------------------
do_summary() {
    [ -f "$TIMINGS" ] || { say "no timings recorded"; return 0; }
    local total
    total=$(awk -F'\t' '{s += $2} END {print s + 0}' "$TIMINGS")
    {
        echo "### chart-kind ($PROFILE): per-phase timings"
        echo
        echo "| phase | seconds |"
        echo "|---|---:|"
        awk -F'\t' '{printf "| %s | %s |\n", $1, $2}' "$TIMINGS"
        echo "| **total** | **$total** |"
    } >"$WORK/summary.md"
    cat "$WORK/summary.md"
    if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
        cat "$WORK/summary.md" >>"$GITHUB_STEP_SUMMARY"
    fi
}

do_diagnose() {
    set +e
    kubectl get pods -A -o wide
    kubectl get events -A --sort-by=.lastTimestamp | tail -n 60
    local ns pod
    for ns in "$NS" chart-kind-replicas; do
        for pod in $(kubectl get pods -n "$ns" -l app.kubernetes.io/component=api -o jsonpath='{.items[*].metadata.name}' 2>/dev/null); do
            echo "=== $ns/$pod migrate"
            kubectl logs -n "$ns" "$pod" -c migrate --tail=100
            echo "=== $ns/$pod api"
            kubectl logs -n "$ns" "$pod" -c api --tail=100
        done
        kubectl describe pods -n "$ns" 2>/dev/null | tail -n 120
    done
    return 0
}

do_teardown() {
    kind delete cluster --name "$CLUSTER"
}

# `time NAME START_EPOCH`: record a phase the workflow ran itself (the image
# builds are docker/build-push-action steps).
do_time() {
    printf '%s\t%s\n' "$1" "$(($(date +%s) - $2))" >>"$TIMINGS"
}

case "${1:-}" in
    cluster) phase cluster do_cluster ;;
    load) phase load do_load ;;
    dry-run) phase dry-run do_dry_run ;;
    guide) phase guide do_guide ;;
    replicas) phase replicas do_replicas ;;
    summary) do_summary ;;
    diagnose) do_diagnose ;;
    teardown) do_teardown ;;
    time) do_time "$2" "$3" ;;
    *)
        echo "usage: $0 cluster|load|dry-run|guide|replicas|summary|diagnose|teardown|time NAME START" >&2
        exit 2
        ;;
esac
