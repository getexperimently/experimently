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
MANIFEST="$REPO_ROOT/scripts/publish/ships-manifest.txt"
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
[ -f "$MANIFEST" ] || { echo "export: $MANIFEST is missing" >&2; exit 2; }

# Pre-flight, before the multi-minute clone and rewrite: the directories the
# launch plan names as "must have no history in the export" have to be in the
# exclusion file, because that file is the only thing that removes them. This
# costs milliseconds and fails in place of discovering it after the rewrite.
MUST_BE_EXCLUDED=(ee docs/go-to-market public-preview project wip docs/planning)
missing=""
for path in "${MUST_BE_EXCLUDED[@]}"; do
    grep -qxF -- "$path" "$EXCLUDE" || missing="$missing $path"
done
if [ -n "$missing" ]; then
    echo "export: the launch plan requires these to be excluded, and they are not in" >&2
    echo "        $EXCLUDE:$missing" >&2
    exit 2
fi

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
# Every path in every commit's tree. The two cheaper spellings are both wrong
# here, and each was measured on this repository before this one was chosen:
#
#   git log --all --name-only   lists nothing for a merge commit, and main has
#                               34 of them. A file added in a merge is in
#                               `git ls-files` and reported zero times by this.
#   git rev-list --objects      lists each OBJECT once, at one path. Identical
#                               blobs share an object, so a file that also
#                               exists at a kept path is reported only there --
#                               194 paths on main are invisible to it, among
#                               them 2-Week-JavaScript-React-Learning-Plan.md.
#
# `ls-tree -r` per commit has neither blind spot: it asks each tree what is in
# it. 327 commits take under two seconds, which is nothing against a clone and
# a history rewrite.
all_paths() {  # $1 = repository
    git -C "$1" rev-list --all | while read -r commit; do
        git -C "$1" ls-tree -r --name-only "$commit" || return 1
    done | sort -u
}
all_paths "$WORK" > "$LOGS/history-paths-before.txt"

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
all_paths "$WORK" > "$LOGS/history-paths.txt"
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

# An empty enumeration makes every assertion below vacuous, and "0 paths, 0
# matches" reads exactly like a clean export. Anything that breaks `all_paths`
# -- a rewrite that left the repository unreadable, a missing ref, a full disk
# -- must fail here rather than report success over a history nobody looked at.
if not paths:
    print("0 paths ever in history -- the enumeration produced nothing")
    sys.exit(1)
if not rules:
    print("exclude-paths.txt parsed to 0 rules")
    sys.exit(1)

print(f"{len(paths)} paths ever in history, {len(bad)} still match an exclusion")
sys.exit(1 if bad else 0)
PY
result "excluded paths absent from history" $? "$(tail -1 "$LOGS/history-check.txt")"

# 3a-ii. The same question, asked the other way round.
#
#     The sweep above derives its patterns FROM the exclusion file, so it can
#     only report entries somebody already thought to write down. That is not
#     a hypothetical weakness: `docs/go-to-market` was named in the launch
#     plan's acceptance list, never added to the exclusion file, and the sweep
#     passed for months while eleven files -- the GTM strategy, the competitor
#     comparison, the design partner playbook, the messaging framework -- sat
#     in the history the export publishes. The first fix for that added the
#     missing entries and asserted them by name, which is circular: every name
#     asserted was also in the exclusion file, so the check could only fire if
#     someone edited that file, and `TRANSITION_TO_COMMERCIAL.md`,
#     `docs/deployment/MARKETING_WEBSITE_GUIDE.md` and `ee-manifest.txt` were
#     still shipping while it passed.
#
#     So this one is a positive manifest. Reduce the rewritten history to its
#     top-level entries plus its `docs/` subdirectories and fail on anything
#     that is not in ships-manifest.txt. An unlisted directory is a FAILURE by
#     default, which is the only shape in which forgetting is caught.
python3 - "$MANIFEST" "$LOGS/history-paths.txt" > "$LOGS/manifest-check.txt" 2>&1 <<'PY'
import sys

allowed = set()
for line in open(sys.argv[1]):
    line = line.split("#", 1)[0].strip()
    if line:
        allowed.add(line)

paths = [p.strip() for p in open(sys.argv[2]) if p.strip()]

unlisted = {}
for path in paths:
    parts = path.split("/")
    top = parts[0]
    if top not in allowed:
        unlisted.setdefault(top, []).append(path)
        continue
    if top == "docs" and len(parts) >= 3:
        sub = "docs/" + parts[1]
        if sub not in allowed:
            unlisted.setdefault(sub, []).append(path)

for entry in sorted(unlisted):
    examples = sorted(unlisted[entry])
    print(f"{entry}  ({len(examples)} paths, e.g. {examples[0]})")

if not paths:
    print("0 paths in the exported history -- the enumeration produced nothing")
    sys.exit(1)

print(f"{len(paths)} paths, {len(allowed)} manifest entries, {len(unlisted)} unlisted")
sys.exit(1 if unlisted else 0)
PY
MANIFEST_STATUS=$?
result "every published directory is on the ships manifest" "$MANIFEST_STATUS" \
    "$(tail -1 "$LOGS/manifest-check.txt")"

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
#
#     The second group is a SHAPE, not a literal list, and it is here because
#     the literal list failed: README.md carried "847 automated tests with 100%
#     pass rate", "82% code coverage", "89% cache hit rate", "8M+
#     invocations/month" and "1.8M+ events/day" -- describing a production
#     deployment that has never existed -- and this sweep reported
#     `PASS  forbidden claims and identifiers  none` over every one of them,
#     because none of those literals was in the list. A deny-list of specific
#     numbers can only catch the numbers someone already noticed, which is the
#     same failure the ships-manifest replaced for paths.
#
#     So: an operational metric with no deployment behind it is matched by its
#     form. `<n>% <hit rate|pass rate|uptime|of users>` and `<n>M+/K+/B+
#     <invocations|events|requests|users>` are claims about a running system;
#     this project has none. A throughput floor an automated test asserts is
#     fine and reads differently, PROVIDED the claim about where it is asserted
#     is true. It was not: the first version of this comment, and the README it
#     describes, said the floors were "asserted on every run" and "asserted in
#     CI" -- while `test_performance_benchmarks.py` carries
#     `skipif(os.environ.get("CI") == "true")` and runs in zero CI runs. A
#     replacement claim has to be measured like any other.
CLAIMS='214117827798|/Users/ashishmarkanday|99\.97|58M\+|2\.8M\+|SOC 2 Type II|GDPR Compliant|SRM detection|1B\+|"environment": "Production"|Enterprise Edition|Community Edition|licen[cs]e key'
git -C "$WORK" grep -nE "$CLAIMS" -- . ':!*package-lock.json' ':!*.lock' ':!scripts/publish/' > "$LOGS/claims.txt" 2>&1
claims_status=$?

#     The unmeasured-metric sweep, run separately because it needs a different
#     pathspec and a filter. Its first run found 14 hits, of which 6 were real
#     and 8 were shapes that are legitimate:
#
#       legitimate  a test ASSERTING a floor ("> 95% hit rate" in
#                   feature_flag_evaluation/tests/performance/) -- so test
#                   trees are excluded;
#       legitimate  a coverage TARGET ("minimum 80% coverage" in the
#                   development guidelines) -- so lines stating a target or a
#                   bound are filtered out;
#       legitimate  a seed script saying what it generates locally
#                   ("100K+ events") -- so demo/ is excluded;
#       legitimate  a caveat that COUNTS the suite honestly while saying it
#                   proves less than it looks ("~4,600 automated tests but no
#                   human has walked through the product").
#
#     What remained were real: README.md's five, and "71 tests, 92% coverage,
#     production-ready" in two documents.
# `%\+? +([a-z]+ +)?` -- one optional word between the number and the keyword.
# Without it `82% code coverage` did not match, and that is one of the five
# README lines the comment above says this catches: the tamper that "proved"
# the pattern restored only three of the five.
UNMEASURED='[0-9]+(\.[0-9]+)?%\+? +([a-z]+ +)?(cache hit|hit rate|pass rate|uptime|coverage)'
UNMEASURED="$UNMEASURED"'|[0-9]+(\.[0-9]+)?[MKB]\+ (invocations|events|requests|users|assignments)'
UNMEASURED="$UNMEASURED"'|[0-9]+ automated tests with'
git -C "$WORK" grep -nE "$UNMEASURED" -- . \
        ':!*package-lock.json' ':!*.lock' ':!scripts/publish/' \
        ':!*tests/*' ':!*test_*.py' ':!*_test.py' ':!demo/*' \
    | grep -vE '\bminimum\b|\bat least\b|\btargets?\b|\brequired\b|>=|> [0-9]|\bthreshold\b' \
    > "$LOGS/unmeasured.txt" || true
# `|| true` on the PIPELINE above is safe -- an empty result is the pass case
# and is checked by size below, not by status. The `git grep` that could fail
# silently is the one whose status IS checked, at `claims_status`.

unmeasured_hits=$(wc -l < "$LOGS/unmeasured.txt" | tr -d ' ')
if [ "$unmeasured_hits" -gt 0 ]; then
    cat "$LOGS/unmeasured.txt" >> "$LOGS/claims.txt"
fi

case $claims_status in
    0) result "forbidden claims and identifiers" 1 "$(wc -l < "$LOGS/claims.txt" | tr -d ' ') hits (see claims.txt)" ;;
    1) if [ "$unmeasured_hits" -gt 0 ]; then
           result "forbidden claims and identifiers" 1 "$unmeasured_hits unmeasured metrics (see claims.txt)"
       else
           result "forbidden claims and identifiers" 0 "none"
       fi ;;
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
