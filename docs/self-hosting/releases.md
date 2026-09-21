# Releases, images and verification

Experimently releases are cut by CI from a tag. Nothing is built or published
from a laptop, and the version a running deployment reports is the same string
the tag, the wheel and the image label carry.

## One version, five places

`VERSION` at the repository root is the source. Everything else derives from
it:

| Place | How it gets the version |
|---|---|
| `settings.VERSION`, `/health`, `GET /api/v1/modules` | `backend/app/core/version.py` reads the file (the image copies it to `/app/VERSION`) |
| the Python distribution | `pyproject.toml`'s `dynamic = ["version"]` reads the file at build time |
| `org.opencontainers.image.version` on both images | the release workflow passes `--build-arg VERSION` |
| `.release-please-manifest.json` | release-please maintains it alongside `VERSION` |
| the git tag | `vX.Y.Z`, written by release-please |

`scripts/check_version_sources.py` fails when any of them disagree. It runs in
the test suite on every pull request and again in the release workflow, with
`--expect <tag>`, before anything is pushed. A drift is not cosmetic: a build
that cannot read `VERSION` does not fail — setuptools warns and stamps
`0.0.0` — so the gate is the only thing between that and a published wheel.

## Cutting a release

1. Merge work to `main` with [conventional commit][cc] subjects (`feat:`,
   `fix:`, `perf:`, `deps:`, `docs:`, `build:`).
2. `release-please` keeps a standing pull request that accumulates them.
   Merging it writes `CHANGELOG.md`, bumps `VERSION` and the manifest, tags the
   merge commit `vX.Y.Z` and opens a GitHub release.
3. `release.yml` then builds, signs and publishes. It is *called* by
   `release-please.yml` rather than triggered by the tag, because a tag pushed
   with the default `GITHUB_TOKEN` does not start another workflow.

A pre-release is cut by pushing the tag by hand — `git tag v1.2.0-rc.1 && git
push origin v1.2.0-rc.1` — which does start `release.yml`. Pre-release tags
publish the versioned image tags but deliberately do **not** move the floating
`:core` / `:full` tags.

[cc]: https://www.conventionalcommits.org/

## What a release publishes

For version `X.Y.Z`, in the repository's GitHub Container Registry namespace:

| Image | Platforms |
|---|---|
| `…/experimently:core-X.Y.Z` | `linux/amd64` |
| `…/experimently:full-X.Y.Z` | `linux/amd64` |
| `…/experimently-web:core-X.Y.Z` | `linux/amd64` |
| `…/experimently-web:full-X.Y.Z` | `linux/amd64` |

A final release also moves `:core` and `:full` to point at it.

**Every image is `amd64` only, and an `arm64` host runs them under emulation.**

The API images used to publish an `arm64` variant. It did not work: in it,
`import cryptography.hazmat.backends.openssl` exits 132 — SIGILL, no traceback,
no message — so every module that imports `backend.app.core.security`, which is
the whole API, was unimportable. An `arm64` host pulling `:core` therefore got
an image that died at import with nothing to explain why. Not publishing it is
better: Docker then falls back to the `amd64` image under emulation, which
runs. Tracked as #181; if `arm64` is wanted later it needs that fixed first and
an `arm64` leg in CI so it cannot regress silently.

The dashboard images are `amd64` only for a different and happier reason: their payload is a static
Next.js export, which is byte-identical on every architecture, but the
Dockerfile builds it inside the image — an `arm64` variant would mean running
`next build` under emulation for no difference in what nginx serves. On an
`arm64` host the image runs under emulation (nginx serving static files), or
build locally, which is what `docker compose up` does anyway.

## Verifying what you pulled

Every image is signed with [cosign][cosign] keyless — the signature is bound to
the workflow's OIDC identity and recorded in Rekor, so there is no key to
leak — and carries an SPDX SBOM as a Sigstore attestation. The same SBOMs are
attached to the GitHub release.

!!! note "The API images' SBOM describes `linux/amd64`"

    It is generated on an `amd64` runner and attested against the whole
    multi-architecture index, so verifying the `arm64` variant succeeds and
    returns the `amd64` package list. Both variants come from one Dockerfile
    and one hashed dependency lock, so the Python distributions are the same;
    the base OS layer is not separately described. Per-platform SBOMs are a
    known gap, not a claim this page is making.

```bash
IMAGE=ghcr.io/<owner>/<repo>:core-X.Y.Z

cosign verify "$IMAGE" \
  --certificate-identity-regexp '^https://github.com/<owner>/<repo>/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com

cosign verify-attestation --type spdxjson "$IMAGE" \
  --certificate-identity-regexp '^https://github.com/<owner>/<repo>/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

The image also states its own version and profile, which is the quickest check
that a deployment is running what you think:

```bash
docker inspect --format '{{index .Config.Labels "org.opencontainers.image.version"}}' "$IMAGE"
docker inspect --format '{{index .Config.Labels "io.experimently.profile"}}' "$IMAGE"
curl -s localhost:8000/api/v1/modules   # {"profile": …, "modules": […], "version": …}
```

[cosign]: https://docs.sigstore.dev/cosign/overview/

## SDK releases

SDKs version independently of the platform — a fix to the JavaScript client
should not force a release of the API images — so each is released by its own
tag, in the form Go requires for a module in a subdirectory and reused for all
of them:

```
sdk/js/v1.2.3
sdk/python/v1.2.3
sdk/go/v1.2.3
```

`sdk-release.yml` publishes to PyPI and npm by trusted publishing (OIDC — no
long-lived token in any secret), behind the `sdk-release` environment. An SDK
with no registry account yet is listed as `unwired` in
`scripts/check_sdk_version.py`, and tagging one is refused rather than quietly
publishing nothing; `backend/tests/smoke/test_sdk_release_wiring.py` fails if
an SDK in the tree is missing from that list altogether.
