# Releases, images and verification

Experimently releases are cut by CI from a tag. Nothing is built or published
from a laptop, and the version a running deployment reports is the same string
the tag, the wheel and the image label carry.

## One version, seven places

`VERSION` at the repository root is the source. Everything else derives from
it:

| Place | How it gets the version |
|---|---|
| `settings.VERSION`, `/health`, `GET /api/v1/modules` | `backend/app/core/version.py` reads the file (the image copies it to `/app/VERSION`) |
| the Python distribution | `pyproject.toml`'s `dynamic = ["version"]` reads the file at build time |
| `org.opencontainers.image.version` on both images | the release workflow passes `--build-arg VERSION` |
| `.release-please-manifest.json` | release-please maintains it alongside `VERSION` |
| `charts/experimently/Chart.yaml` `version` and `appVersion` | release-please rewrites both lines through their `# x-release-please-version` markers; `appVersion` is the chart's default image tag (`<profile>-<appVersion>`) |
| the two image lines of `deploy/compose/compose.yml` | release-please rewrites them the same way |
| the git tag | `vX.Y.Z`, written by release-please |

`scripts/check_version_sources.py` fails when any of them disagree. The chart
lines and the compose image lines must be spelled exactly as `VERSION`, since
they become image tags and the chart's file name. It runs in
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
`:core` / `:full` tags, and they do not deploy the documentation site: only a
release tag with no `-` in it publishes the docs, so a release candidate never
replaces the live site.

[cc]: https://www.conventionalcommits.org/

## What a release publishes

For version `X.Y.Z`, in the repository's GitHub Container Registry namespace:

| Image | Platforms |
|---|---|
| `…/experimently:core-X.Y.Z` | `linux/amd64` |
| `…/experimently:full-X.Y.Z` | `linux/amd64` |
| `…/experimently-web:core-X.Y.Z` | `linux/amd64` |
| `…/experimently-web:full-X.Y.Z` | `linux/amd64` |

A final release also moves `:core` and `:full` to point at it, and only once
everything else in the release, including the chart below, has succeeded.

Each image is scanned for stored credentials with trivy's secret scanner
before it is pushed, and a finding stops that image and the release. The
claim is that the scan found nothing, not that the image is proven to hold no
credential. There are two scans:

- **The whole image, with trivy's default rules.** Those rules skip
  `/usr/share` and `/usr/lib`, `vendor/` and `locale/` directories, `*.md`
  files, file names containing `example` or `_test`, and `node_modules/`
  (trivy skips that one even with every rule turned off).
- **This project's own files, with every rule turned off.** These are `/app`
  in the API images, and `/usr/share/nginx/html` and `/etc/nginx` in the
  dashboard images. They are copied out of the image without running it.

So the remaining gap is third-party files on the paths the default rules
skip. After the push, the release checks that the pushed image's layers are
the layers it scanned, before signing it.

The GitHub release also carries the Helm chart as `experimently-X.Y.Z.tgz`,
packaged from the tagged tree after `helm lint --strict`. Before it is
attached, `scripts/check_chart_package.py` reads the `Chart.yaml` inside the
archive and requires its `version` and `appVersion` to be exactly `X.Y.Z`, so
the chart installs the images of the same release. The chart is a release
asset only; it is not pushed to a chart registry.

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

### If the credential scan fails

The image job fails at "Scan the image for stored credentials" or "Scan the
payload with every allow rule off". Its summary lists each finding's file
path in the image, rule, severity and line. The matched text is never
printed, because the log of a public repository's run is public.

1. **Know what was published.** The failed image was not pushed. The other
   image jobs may have pushed their versioned tags, because each image is
   built separately. No SBOMs or chart are attached to the GitHub release,
   and `:core` and `:full` stay on the previous release. The git tag exists,
   and release-please may already have opened the GitHub release.
2. **Revoke and replace the credential first.** An image is built from the
   tagged tree, so a credential in the image is almost certainly in the
   repository's public history too. Removing the file does not undo that.
3. **Remove the file from the image and cut a new patch release.**
   Re-running the release for the same tag rebuilds the same tree and fails
   the same way.
4. **There is no allow-list.** The workflow passes trivy its own empty
   ignore file, so a finding is fixed by taking the file out of the image,
   never by listing it.
5. **Versioned tags already pushed for the failed version stay** until an
   organization owner deletes those package versions in GitHub Packages. That
   is a manual step.

If "The pushed image is the scanned image" fails instead, the pushed layers
differ from the scanned ones. That image's versioned tag has already been
pushed, but it is not signed and nothing else in the release continues. An
organization owner deletes that package version, and the release is then
re-run for the same tag: `gh workflow run release.yml -f tag=vX.Y.Z`.

## Verifying what you pulled

Every image is signed with [cosign][cosign] keyless — the signature is bound to
the workflow's OIDC identity and recorded in Rekor, so there is no key to
leak — and carries an SPDX SBOM as a Sigstore attestation. The same SBOMs are
attached to the GitHub release.

!!! note "The SBOMs describe `linux/amd64`"

    That is the only platform published, so each SBOM describes the whole
    image. If a second platform is ever added, one SBOM would be attested
    against the multi-architecture index and the release notes say so;
    per-platform SBOMs would be needed first.

You need [cosign][cosign], Docker with Buildx (`docker buildx version` prints
one) and `jq`. Nothing is pulled: every command below reads the registry, and
none needs an account.

Set `IMAGE` to the image you run. `:core` is the newest final release; a
versioned tag such as `:core-0.26.3` is one release, and `full` in place of
`core` is the full profile:

```{.bash exec}
IMAGE=ghcr.io/getexperimently/experimently:core
IDENTITY='^https://github\.com/getexperimently/experimently/\.github/workflows/release\.yml@refs/(heads/main|tags/v[0-9].*)$'
NO_LOGIN=$(mktemp -d)
```

`IDENTITY` names one workflow, this repository's `release.yml`. It accepts
`release.yml` run from `main`, which is how release-please cuts a release and
how `gh workflow run release.yml -f tag=vX.Y.Z` runs one again, and run from a
`v` tag, which is how a tag pushed by hand starts it. A signature made by any
other workflow, repository or branch fails.

`NO_LOGIN` is an empty directory. The two `cosign` commands run with
`DOCKER_CONFIG` pointing at it, so they read no registry login and show that
none is needed.

Check the signature:

```{.bash exec}
DOCKER_CONFIG=$NO_LOGIN cosign verify "$IMAGE" \
  --certificate-identity-regexp "$IDENTITY" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  | jq -r '.[].optional.Subject'
```
<!-- expect: https://github.com/getexperimently/experimently/.github/workflows/release.yml@refs/ -->

It prints the identity in the signing certificate, such as
`https://github.com/getexperimently/experimently/.github/workflows/release.yml@refs/heads/main`.
cosign writes the checks it made to stderr. When no signature matches, it
fails with `no matching signatures`.

Check the SBOM attestation the same way. It prints the attestation's predicate
type, `https://spdx.dev/Document`:

```{.bash exec}
DOCKER_CONFIG=$NO_LOGIN cosign verify-attestation --type spdxjson "$IMAGE" \
  --certificate-identity-regexp "$IDENTITY" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  | jq -r '.payload | @base64d | fromjson | .predicateType'
```
<!-- expect: https://spdx.dev/Document -->

Without the `jq`, it prints the whole attestation, SBOM included: several
megabytes.

The image also states its own version and profile in its labels, which
`docker buildx imagetools inspect` reads from the registry without pulling the
image:

```{.bash exec}
docker buildx imagetools inspect "$IMAGE" --format '{{json .Image.Config.Labels}}' \
  | jq '{version: ."org.opencontainers.image.version", profile: ."io.experimently.profile"}'
```
<!-- expect: "version": " -->
<!-- expect: "profile": "core" -->

It prints the release's version, such as `"version": "0.26.3"`, and
`"profile": "core"`.

A running deployment reports the same two things, which is the quickest check
that it is running what you think:

```{.bash exec}
curl -s localhost:8000/api/v1/modules
```
<!-- expect: "profile":"core" -->

It prints `{"profile":"core","modules":[],"version":…}` on the core profile;
the full profile lists its modules.

[cosign]: https://docs.sigstore.dev/cosign/overview/

## SDK releases

SDKs version independently of the platform — a fix to the JavaScript client
should not force a release of the API images — so each is released by its own
tag, in the form Go requires for a module in a subdirectory and reused for all
of them:

```text
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

A PyPI release (`sdk/python`, `sdk/openfeature-python`) runs in two jobs:

- **test and build for PyPI** installs the SDK, runs its tests, builds the
  wheel and sdist, runs `twine check`, and uploads `dist/` with a digest of
  the files. It cannot request an OIDC token.
- **publish to PyPI** is the only job that can, and the `sdk-release`
  environment's approval is asked for when it starts, after the tests and
  checks above have passed. It installs nothing. It requires every
  downloaded file to be a wheel or sdist with the tag's project name and
  version, nothing else to be present, and the digest to match, and then
  uploads those files.

Write a Python version in its PEP 440 spelling (`1.0.0rc1`, not
`1.0.0-rc.1`), in the manifest and the tag alike; the build job refuses any
other spelling.

An npm release (`sdk/js`, `sdk/edge`, `sdk/openfeature`, `sdk/react`,
`sdk/react-native`) runs in two jobs the same way:

- **test and build for npm** installs the SDK, runs its tests, builds and
  packs it, checks the packed tarball, and uploads it with its file name and
  sha256. It cannot request an OIDC token.
- **publish to npm** is the only job that can, and the `sdk-release`
  environment's approval is asked for when it starts, after the tests and
  checks above have passed. It has no checkout and installs nothing. It
  requires exactly the one tarball the build job recorded, with the same
  sha256, and checks the package it uploads against the tag: the
  `package.json` inside it must have the tag's name and version, and it
  refuses a manifest that sets publish configuration.

A prerelease — a version with a `-`, such as `1.0.0-rc.1` — publishes under
the `next` dist-tag, so `npm install <package>` keeps resolving the last
stable version and `npm install <package>@next` gets the prerelease. A stable
version is published with no `--tag`, and npm gives it `latest`. Make a
package's first npm publish a stable version: whether the registry also
points `latest` at a first publish made under `next` is not something this
workflow decides.

If a publish job fails after approval, use **Re-run failed jobs**, not
**Re-run all jobs**. Re-run failed jobs is meant to reuse the files the build
job checked (not yet seen on a real release).

Publish `sdk/js` before `sdk/openfeature`; the provider's release refuses until
the matching `@getexperimently/js-sdk` is on npm. The provider's source depends
on `file:../js` so that its tests run against the JS SDK in the same tree; the
npm build job rewrites that to `^<sdk/js version>` before packing, checks the
`package.json` inside the packed tarball, installs the tarball in an empty
directory, and uploads that same tarball for the publish job.
