#!/usr/bin/env python3
"""
Live SDK contract runner.

Runs every SDK's ``contract_smoke`` entry point against a running backend and
checks that each one reports a sticky assignment, a flag evaluation and
successful event tracking. This is the test that proves an SDK actually talks
to the endpoints the backend serves (the golden-vector tests only cover
hashing).

Prerequisites
    1. A backend at ``$EXPERIMENTLY_API_URL`` (default http://localhost:8000)
       seeded with ``python backend/scripts/seed_sdk_contract.py`` (creates the
       ``sdk_contract_ab`` experiment, the ``sdk_contract_flag`` flag and an API
       key written to tests/sdk-contract/live/.api_key).
    2. The toolchains of the SDKs you want to run (missing ones are skipped
       unless ``--strict``).

Usage
    python tests/sdk-contract/live/run_live_contract.py            # all available
    python tests/sdk-contract/live/run_live_contract.py --sdk go --sdk python
    python tests/sdk-contract/live/run_live_contract.py --strict   # missing toolchain = failure
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
KEY_FILE = Path(__file__).resolve().parent / ".api_key"

# sdk name -> (shell command run from the repo root, required executables)
MANIFEST: dict[str, tuple[str, tuple[str, ...]]] = {
    "python": ("python sdk/python/examples/contract_smoke.py", ("python",)),
    "openfeature-python": ("python sdk/openfeature-python/examples/contract_smoke.py", ("python",)),
    "js": ("cd sdk/js && npm run build --silent && node examples/contract_smoke.mjs", ("node", "npm")),
    "openfeature": (
        "cd sdk/openfeature && npm run build --silent && node examples/contract_smoke.mjs",
        ("node", "npm"),
    ),
    "edge": ("cd sdk/edge && npm run build --silent && node examples/contract_smoke.mjs", ("node", "npm")),
    "go": ("cd sdk/go && go run ./examples/contract_smoke", ("go",)),
    "java": ("bash sdk/java/examples/contract_smoke.sh", ("java", "mvn")),
    "ios": ("cd sdk/ios && swift run -q contract-smoke", ("swift",)),
    "ruby": ("ruby -Isdk/ruby/lib sdk/ruby/examples/contract_smoke.rb", ("ruby",)),
    "php": ("php sdk/php/examples/contract_smoke.php", ("php",)),
    "dotnet": ("dotnet run --project sdk/dotnet/examples/ContractSmoke", ("dotnet",)),
    "elixir": ("cd sdk/elixir && mix run examples/contract_smoke.exs", ("mix",)),
    "flutter": ("cd sdk/flutter && dart run example/contract_smoke.dart", ("dart",)),
}

EXPECTED_VARIANTS = {"control", "treatment"}


def backend_healthy(api_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{api_url}/health", timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def validate(sdk: str, payload: dict) -> list[str]:
    problems: list[str] = []
    if payload.get("sdk") != sdk:
        problems.append(f"sdk field is {payload.get('sdk')!r}, expected {sdk!r}")
    assign = payload.get("assign") or {}
    if assign.get("variant_name") not in EXPECTED_VARIANTS:
        problems.append(f"assign.variant_name={assign.get('variant_name')!r}")
    if not isinstance(assign.get("is_control"), bool):
        problems.append("assign.is_control is not a bool")
    if assign.get("sticky") is not True:
        problems.append("assignment was not sticky")
    flag = payload.get("flag") or {}
    if flag.get("enabled") is not True:
        problems.append(f"flag.enabled={flag.get('enabled')!r} (seeded flag is 100% on)")
    if (payload.get("track") or {}).get("ok") is not True:
        problems.append("track failed")
    if (payload.get("fanout") or {}).get("ok") is not True:
        problems.append("fan-out track failed")
    return problems


def run_one(sdk: str, command: str, env: dict[str, str], timeout: int) -> tuple[str, str]:
    """Return (status, detail) where status is PASS / FAIL."""
    started = time.time()
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "FAIL", f"timed out after {timeout}s"
    elapsed = time.time() - started
    stdout_lines = [line for line in proc.stdout.strip().splitlines() if line.strip()]
    if proc.returncode != 0:
        tail = (proc.stderr.strip().splitlines() or stdout_lines or ["(no output)"])[-1]
        return "FAIL", f"exit {proc.returncode}: {tail[:300]}"
    if not stdout_lines:
        return "FAIL", "no JSON line on stdout"
    try:
        payload = json.loads(stdout_lines[-1])
    except json.JSONDecodeError:
        return "FAIL", f"last stdout line is not JSON: {stdout_lines[-1][:200]}"
    problems = validate(sdk, payload)
    if problems:
        return "FAIL", "; ".join(problems)
    return "PASS", f"{payload['assign']['variant_name']} in {elapsed:.1f}s"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sdk", action="append", help="run only this SDK (repeatable)")
    parser.add_argument("--strict", action="store_true", help="treat a missing toolchain as a failure")
    parser.add_argument("--timeout", type=int, default=300, help="seconds per SDK (builds included)")
    parser.add_argument("--api-url", default=os.environ.get("EXPERIMENTLY_API_URL", "http://localhost:8000"))
    args = parser.parse_args()

    api_key = os.environ.get("EXPERIMENTLY_API_KEY") or (KEY_FILE.read_text().strip() if KEY_FILE.exists() else "")
    if not api_key:
        print("No API key: set EXPERIMENTLY_API_KEY or run backend/scripts/seed_sdk_contract.py", file=sys.stderr)
        return 2
    if not backend_healthy(args.api_url):
        print(f"Backend at {args.api_url} is not healthy", file=sys.stderr)
        return 2

    env = dict(os.environ)
    env.update({"EXPERIMENTLY_API_URL": args.api_url, "EXPERIMENTLY_API_KEY": api_key})
    env.setdefault("CONTRACT_EXPERIMENT_KEY", "sdk_contract_ab")
    env.setdefault("CONTRACT_FLAG_KEY", "sdk_contract_flag")

    selected = args.sdk or list(MANIFEST)
    unknown = [s for s in selected if s not in MANIFEST]
    if unknown:
        print(f"Unknown SDK(s): {', '.join(unknown)}. Known: {', '.join(MANIFEST)}", file=sys.stderr)
        return 2

    results: list[tuple[str, str, str]] = []
    for sdk in selected:
        command, tools = MANIFEST[sdk]
        missing = [t for t in tools if shutil.which(t) is None]
        if missing:
            results.append((sdk, "FAIL" if args.strict else "SKIP", f"missing toolchain: {', '.join(missing)}"))
            continue
        status, detail = run_one(sdk, command, env, args.timeout)
        results.append((sdk, status, detail))
        print(f"{status:4} {sdk:<20} {detail}", flush=True)

    print("\nSummary")
    for sdk, status, detail in results:
        print(f"  {status:4} {sdk:<20} {detail}")
    failed = [r for r in results if r[1] == "FAIL"]
    passed = [r for r in results if r[1] == "PASS"]
    skipped = [r for r in results if r[1] == "SKIP"]
    print(f"\n{len(passed)} passed, {len(failed)} failed, {len(skipped)} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
