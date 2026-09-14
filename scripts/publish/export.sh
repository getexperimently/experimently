#!/usr/bin/env bash
# Export this repository for publication.
#
# A fresh clone of one ref, with every path in scripts/publish/exclude-paths.txt
# removed from every commit (git filter-repo), followed by the acceptance
# sweep that decides whether the result may be published. The export is
# repeatable: run it as a rehearsal on any branch, and with --push at the cut.
#
#   scripts/publish/export.sh [--ref REF] [--out DIR] [--keep] [--skip-build]
#                             [--push URL [--force-push]]
#
#   --ref REF        the ref to export (default: main)
#   --out DIR        where to put the export (default: a temporary directory)
#   --keep           leave the export in place afterwards (default with --out)
#   --skip-build     do not run scripts/core_build.sh on the export (it takes
#                    ~5 minutes and needs Postgres on localhost:5432)
#   --push URL       push the exported main to URL. Refused if the remote
#                    already has a main, unless --force-push.
#
# Every sweep runs even after one fails, so the summary is complete; the exit
# status is non-zero if any failed. Sweep output goes to files under the
# export's parent directory, never through a pipe that could hide a failure.
#
# Why history and not just the tree: docs/planning/ holds the internal
# strategy, public-preview/ holds fabricated production metrics, the agent
# instruction files hold local absolute paths. Publishing the history would
# publish all of it. The optional modules are NOT removed -- they ship.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXCLUDE="$REPO_ROOT/scripts/publish/exclude-paths.txt"
REF=main
OUT=""
KEEP=0
SKIP_BUILD=0
PUSH_URL=""
FORCE_PUSH=0

while [ $# -gt 0 ]; do
    case "$1" in
        --ref) REF="$2"; shift 2 ;;
        --out) OUT="$2"; KEEP=1; shift 2 ;;
        --keep) KEEP=1; shift ;;
        --skip-build) SKIP_BUILD=1; shift ;;
        --push) PUSH_URL="$2"; shift 2 ;;
        --force-push) FORCE_PUSH=1; shift ;;
        -h|--help) sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "export: unknown argument '$1'" >&2; exit 2 ;;
    esac
done

for tool in git git-filter-repo gitleaks trufflehog python3; do
    command -v "$tool" >/dev/null || { echo "export: $tool is not installed" >&2; exit 2; }
done
[ -f "$EXCLUDE" ] || { echo "export: $EXCLUDE is missing" >&2; exit 2; }

if [ -z "$OUT" ]; then
    OUT="$(mktemp -d "${TMPDIR:-/tmp}/experimently-export.XXXXXX")"
fi
WORK="$OUT/export"
LOGS="$OUT/logs"
mkdir -p "$LOGS"
rm -rf "$WORK"

log() { printf '[export] %s\n' "$*"; }

# ---------------------------------------------------------------------------
# 1. A fresh clone of exactly one ref. --no-local so filter-repo sees a real
#    clone (it refuses to rewrite a repository that is not one), --single-branch
#    so nothing but the exported ref's history is carried across.
# ---------------------------------------------------------------------------
log "cloning $REF into $WORK"
git clone --quiet --no-local --no-hardlinks --branch "$REF" --single-branch "$REPO_ROOT" "$WORK" \
    || { echo "export: clone failed" >&2; exit 1; }
COMMITS_BEFORE=$(git -C "$WORK" rev-list --count HEAD)
# Every path that ever existed, BEFORE the rewrite: the dangling-reference
# check needs to know which excluded entries were directories, and after the
# rewrite they no longer exist anywhere to ask.
git -C "$WORK" log --all --name-only --format= | sort -u > "$LOGS/history-paths-before.txt"

# ---------------------------------------------------------------------------
# 2. Rewrite history. filter-repo drops the origin remote afterwards on
#    purpose: a rewritten history must never be pushed back where it came from.
# ---------------------------------------------------------------------------
log "removing $(grep -cvE '^\s*(#|$)' "$EXCLUDE") excluded paths from every commit"
(cd "$WORK" && git filter-repo --invert-paths --paths-from-file "$EXCLUDE" --quiet) > "$LOGS/filter-repo.log" 2>&1 \
    || { echo "export: git filter-repo failed (see $LOGS/filter-repo.log)" >&2; exit 1; }
COMMITS_AFTER=$(git -C "$WORK" rev-list --count HEAD)
if [ "$REF" != "main" ]; then
    git -C "$WORK" branch -M "$REF" main
fi
log "history rewritten: $COMMITS_BEFORE commits -> $COMMITS_AFTER"

# ---------------------------------------------------------------------------
# 3. The sweep. Each check writes PASS/FAIL to the summary and its evidence to
#    a log; none of them stops the others.
# ---------------------------------------------------------------------------
declare -a SUMMARY=()
FAILED=0
result() {  # $1 = name, $2 = 0|1 (0 = pass), $3 = detail
    if [ "$2" -eq 0 ]; then SUMMARY+=("PASS  $1  $3"); else SUMMARY+=("FAIL  $1  $3"); FAILED=1; fi
}

# 3a. Nothing excluded survives anywhere in the rewritten history. The check
#     re-derives the rules from exclude-paths.txt with the same semantics
#     filter-repo applies, over every path that ever existed.
git -C "$WORK" log --all --name-only --format= | sort -u > "$LOGS/history-paths.txt"
python3 - "$EXCLUDE" "$LOGS/history-paths.txt" > "$LOGS/history-check.txt" 2>&1 <<'PY'
import fnmatch, sys
rules = []
for line in open(sys.argv[1]):
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    rules.append(line)
paths = [p.strip() for p in open(sys.argv[2]) if p.strip()]
bad = []
for path in paths:
    for rule in rules:
        if rule.startswith("glob:"):
            if fnmatch.fnmatch(path, rule[5:]):
                bad.append((path, rule)); break
        elif path == rule or path.startswith(rule.rstrip("/") + "/"):
            bad.append((path, rule)); break
for path, rule in bad:
    print(f"{path}  (matches {rule})")
print(f"{len(paths)} paths ever in history, {len(bad)} still match an exclusion")
sys.exit(1 if bad else 0)
PY
result "excluded paths absent from history" $? "$(tail -1 "$LOGS/history-check.txt")"

# 3b. Secrets, full history, with the default rules and NO path allowlist.
#     scripts/publish/gitleaks-export.toml extends the defaults (a config
#     that does not is a config with no rules -- see the comment there) and
#     allowlists only a reviewed list of literal placeholder values. The
#     repository's own .gitleaks.toml is deliberately not used: it exempts the
#     test directories, and tests are published too.
gitleaks detect --source "$WORK" --log-opts='--all' --no-banner --redact \
    -c "$REPO_ROOT/scripts/publish/gitleaks-export.toml" -r "$LOGS/gitleaks.json" > "$LOGS/gitleaks.log" 2>&1
result "gitleaks (all history, default rules, no path allowlist)" $? "$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))), 'findings')" "$LOGS/gitleaks.json" 2>/dev/null || echo 'see gitleaks.log')"

# 3c. Verified secrets, full history.
trufflehog git "file://$WORK" --only-verified --fail --no-update --json > "$LOGS/trufflehog.json" 2> "$LOGS/trufflehog.log"
result "trufflehog --only-verified" $? "$(grep -c '"Verified":true' "$LOGS/trufflehog.json" 2>/dev/null || true) verified"

# 3d. The claims and identifiers the launch checklist forbids in the tree.
#     `Type II` alone matches the statistics docs; lock files carry `1B+`
#     inside integrity hashes.
CLAIMS='214117827798|/Users/ashishmarkanday|99\.97|58M\+|2\.8M\+|SOC 2 Type II|GDPR Compliant|SRM detection|1B\+|"environment": "Production"|Enterprise Edition|Community Edition|licen[cs]e key'
git -C "$WORK" grep -nE "$CLAIMS" -- . ':!*package-lock.json' ':!*.lock' ':!scripts/publish/' > "$LOGS/claims.txt" 2>&1
case $? in
    0) result "forbidden claims and identifiers" 1 "$(wc -l < "$LOGS/claims.txt" | tr -d ' ') hits (see claims.txt)" ;;
    1) result "forbidden claims and identifiers" 0 "none" ;;
    *) result "forbidden claims and identifiers" 1 "git grep failed (see claims.txt)" ;;   # an error is not a pass
esac

# 3e. No surviving file refers to a removed path (a dead link in the public
#     tree). One pattern per entry, derived from the exclusion file: a removed
#     *directory* must be referenced with a trailing slash (`project/`, so the
#     word "project" is not a hit), a removed *file* as its full path; either
#     way not preceded by `~/` (a home directory) or another path character.
#     Entries under the "local files" marker are things a developer creates
#     locally -- the docs may name them -- and are not link targets.
python3 - "$EXCLUDE" "$LOGS/history-paths-before.txt" > "$LOGS/dangling-patterns.txt" <<'PY'
import re, sys
history = [p.strip() for p in open(sys.argv[2]) if p.strip()]
linkable = True
for line in open(sys.argv[1]):
    line = line.strip()
    if line.startswith("# --- local files"):
        linkable = False
    if not line or line.startswith("#") or line.startswith("glob:") or not linkable:
        continue
    is_dir = any(h.startswith(line.rstrip("/") + "/") for h in history)
    # POSIX ERE (what git grep -E uses on macOS) has no \b: "not followed by
    # a path character" is the portable spelling of "the whole file name".
    # A trailing "." is allowed: "see CLAUDE.md." ends a sentence more often
    # than it names CLAUDE.md.bak.
    tail = "/" if is_dir else r"([^[:alnum:]_/-]|$)"
    # re.escape writes a hyphen as \- which POSIX ERE leaves undefined; [-] is
    # the portable spelling.
    print(r"(^|[^~[:alnum:]_/.-])" + re.escape(line).replace(r"\-", "[-]") + tail)
PY
: > "$LOGS/dangling.txt"
GREP_ERRORS=0
while IFS= read -r pattern; do
    git -C "$WORK" grep -nE "$pattern" -- . ':!scripts/publish/' ':!.gitignore' ':!.dockerignore' >> "$LOGS/dangling.txt" 2>> "$LOGS/dangling-errors.txt"
    rc=$?
    # 0 = hits (recorded), 1 = none; anything else is a broken pattern, and a
    # check that silently skips a pattern is a check that cannot fail.
    [ "$rc" -le 1 ] || { GREP_ERRORS=$((GREP_ERRORS + 1)); echo "pattern failed (rc=$rc): $pattern" >> "$LOGS/dangling-errors.txt"; }
done < "$LOGS/dangling-patterns.txt"
if [ "$GREP_ERRORS" -ne 0 ]; then
    result "no references to removed paths" 1 "$GREP_ERRORS pattern(s) failed to run (see dangling-errors.txt)"
elif [ -s "$LOGS/dangling.txt" ]; then
    result "no references to removed paths" 1 "$(wc -l < "$LOGS/dangling.txt" | tr -d ' ') references (see dangling.txt)"
else
    result "no references to removed paths" 0 "none ($(wc -l < "$LOGS/dangling-patterns.txt" | tr -d ' ') patterns)"
fi

# 3f. The core profile builds and passes its suites from the export. The
#     export has no node_modules; borrow this checkout's for the duration.
if [ "$SKIP_BUILD" -eq 0 ]; then
    if [ -d "$REPO_ROOT/frontend/node_modules" ] && [ ! -e "$WORK/frontend/node_modules" ]; then
        ln -s "$REPO_ROOT/frontend/node_modules" "$WORK/frontend/node_modules"
        BORROWED=1
    else
        BORROWED=0
    fi
    (cd "$WORK" && PYTHON="${PYTHON:-$REPO_ROOT/venv/bin/python}" scripts/core_build.sh) > "$LOGS/core_build.log" 2>&1
    rc=$?
    [ "$BORROWED" -eq 1 ] && rm -f "$WORK/frontend/node_modules"
    result "core_build.sh on the export" $rc "$(grep -E '^core-build:' "$LOGS/core_build.log" | tail -1)"
else
    SUMMARY+=("SKIP  core_build.sh on the export  (--skip-build)")
fi

# ---------------------------------------------------------------------------
# 4. Summary, then push only if everything passed.
# ---------------------------------------------------------------------------
echo
echo "export of $REF: $COMMITS_BEFORE -> $COMMITS_AFTER commits, $(git -C "$WORK" ls-files | wc -l | tr -d ' ') files"
printf '  %s\n' "${SUMMARY[@]}"
echo "  logs: $LOGS"

if [ "$FAILED" -ne 0 ]; then
    echo "export: FAILED -- not publishable" >&2
    [ "$KEEP" -eq 1 ] || echo "  (export kept for inspection: $WORK)"
    exit 1
fi

if [ -n "$PUSH_URL" ]; then
    git -C "$WORK" remote add public "$PUSH_URL"
    if git -C "$WORK" ls-remote --exit-code --heads public main > /dev/null 2>&1 && [ "$FORCE_PUSH" -eq 0 ]; then
        echo "export: $PUSH_URL already has a main; pass --force-push to replace it" >&2
        exit 1
    fi
    log "pushing main to $PUSH_URL"
    git -C "$WORK" push public main $( [ "$FORCE_PUSH" -eq 1 ] && echo --force ) || exit 1
fi

if [ "$KEEP" -eq 0 ]; then
    rm -rf "$OUT"
else
    echo "  export: $WORK"
fi
echo "export: OK"
