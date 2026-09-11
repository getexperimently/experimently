# SDK contract tests

Two layers keep the SDKs honest.

## 1. Golden vectors (offline)

`golden-vectors.json` fixes the MD5 consistent-hash function every SDK exports
(`{userId}:{flagKey}` → first 4 bytes little-endian ÷ 2^32). `test_python_sdk.py` and
`test_js_sdk.js` check the reference implementations; each SDK's own unit tests check its port.
These run in the `SDK Contract Tests` job of the PR gate and need no backend.

```bash
python -m pytest tests/sdk-contract/test_python_sdk.py -q -o addopts=""
node tests/sdk-contract/test_js_sdk.js
```

The hash is a utility only. Since the September 2026 SDK rewiring no SDK buckets users locally: assignment and flag
evaluation are decided by the backend.

## 2. Live contract (against a running backend)

`live/run_live_contract.py` runs every SDK's `contract_smoke` entry point against a real backend
and checks the JSON it prints: a sticky assignment (`control` / `treatment`), a flag evaluation
(`enabled: true`), one tracked event with an experiment key, and one key-less event that fans out
to the cached assignment and flag.

```bash
source venv/bin/activate
export APP_ENV=development POSTGRES_SERVER=localhost POSTGRES_DB=experimentation POSTGRES_SCHEMA=experimentation

python backend/scripts/seed_sdk_contract.py          # experiment sdk_contract_ab, flag sdk_contract_flag, API key -> live/.api_key
uvicorn backend.app.main:app --port 8000 &            # or ./demo/setup-local.sh
python tests/sdk-contract/live/run_live_contract.py   # all SDKs whose toolchain is installed
python tests/sdk-contract/live/run_live_contract.py --sdk go --sdk python --strict
```

Each SDK documents its smoke command in its README; the runner's `MANIFEST` lists them. Missing
toolchains are skipped (reported as `SKIP`) unless `--strict` is given. The seeded API key can be
overridden with `EXPERIMENTLY_API_KEY`, the backend with `EXPERIMENTLY_API_URL`.

Contract details (endpoints, bodies, fan-out rule, smoke output format) live in
`docs/sdk-guide.md` ("Endpoint contract").
