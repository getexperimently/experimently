# SDK contract tests

Two layers keep the SDKs honest.

## 1. Golden vectors (offline)

`golden-vectors.json` fixes the MD5 consistent-hash function every SDK exports
(`{userId}:{flagKey}` → first 4 bytes little-endian ÷ 2^32). `hash_contract.py` runs each SDK's
**own** exported function against it -- not a copy of the algorithm -- through a thin harness per
SDK in `harness/`, and does every comparison itself: the hash (within 1e-10, less than one bucket),
the MD5 digest where the SDK exports one, the rollout inclusions, and exactly 9 hash vectors and
2 rollout vectors answered by each SDK.

| SDK | What runs | Needs |
| --- | --- | --- |
| `python` | `experimentation.consistent_hash` / `md5_hex` from `sdk/python` | python |
| `js` | `consistentHash` / `md5Hex` from the built package (`npm ci && npm run build` in `sdk/js`) | node |
| `edge` | `hashUser` / `md5Hex` from the built package (`sdk/edge`) | node |
| `react-native` | `hashUser` from `src/hash.ts`, loaded with node's type stripping (the package ships source) | node 22 |
| `go` | `ConsistentHash`, compiled from `sdk/go` through a `replace` directive | go |

`--list` names every other `sdk/` directory and why this job does not run it (iOS needs
CommonCrypto, Android a Kotlin build; their own hash tests run in `sdk-unit-tests.yml`), and fails
on a directory it does not classify. These run in the `SDK Contract Tests` job of the PR gate, one
step per SDK, and need no backend. The pytest run is the comparison's own tests.

```bash
python tests/sdk-contract/hash_contract.py --list
python -m pytest tests/sdk-contract -q -o addopts=""
python tests/sdk-contract/hash_contract.py python js edge react-native go
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

Three entries need no toolchain beyond node or a JVM, but get there differently from the rest:

| SDK | How it runs under the contract |
| --- | --- |
| `react` | `sdk/react/examples/contract_smoke.mjs` drives the SSR entry point (`ServerClient`) plus `ExperimentationClient` for tracking, under plain node — no DOM, no React render. `trackEvent` never throws, so the smoke wraps `fetch` and fails on any tracking call that did not return 2xx. |
| `react-native` | A Jest test (`sdk/react-native/examples/contract_smoke.test.ts`, `jest.contract.config.js`) under `testEnvironment: node` with the in-memory AsyncStorage mock — no device, emulator or Metro. The package ships no build output, so Jest's ts-jest transform is the build. Jest owns stdout, so the report is written to `.contract_smoke.json` and the MANIFEST command `cat`s it. |
| `android` | `sdk/android/jvm/` compiles the Android SDK's Kotlin sources for a plain JVM (they touch no `android.*` API) with Maven, and `sdk/android/examples/contract_smoke.sh` runs the smoke from that build — no Android SDK, no emulator. The same module runs the SDK's 78 unit tests: `cd sdk/android/jvm && ./mvnw clean test`. |

Contract details (endpoints, bodies, fan-out rule, smoke output format) live in
`docs/sdk-guide.md` ("Endpoint contract").
