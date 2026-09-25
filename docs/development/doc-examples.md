# Runnable Documentation Examples

The shell examples on an enrolled page are held to a contract: every shell block says
whether it runs, a block that runs states what it prints, and the block renders as code
on the site and on GitHub. `scripts/doc_examples.py` checks all of it on every pull
request (the `doc-examples` workflow). A page fails when:

- a shell block is left untagged, or tagged in a form the site would break;
- a block contains something a reader can't paste as written;
- the counts of blocks and expectations stop matching the enrolment file;
- a tagged block renders as a paragraph instead of code.

Running the examples against a real stack is the next step and is not enabled yet; the
parts of this page about running describe how it will work.

---

## Is my page enrolled?

Enrolled pages are listed in `scripts/doc_examples.toml`. Each entry names the page, the
environment it will run in, and its exact counts of `exec` blocks, `skip` blocks and
expectations:

```toml
[[document]]
path = "docs/getting-started/quick-start.md"
environment = "bare"
exec = 11
skip = 3
expects = 11
```

If your edit changes a count, update the entry in the same pull request. The check prints
the counts it finds, and fails naming both numbers if they differ. Never change a number
just to make the check pass: find out why it moved.

---

## Tagging a shell block

Every fenced block whose language is `bash`, `sh`, `shell` or `console` carries exactly
one tag, in braces.

**Run it:**

````markdown
```{.bash exec}
curl -s localhost:8000/health/ready | jq .status
```
````

**Don't run it, and say why.** The reason is required. It's visible to anyone reading the
page source, so write it for them:

````markdown
```{.bash skip reason="starts a long-running development server"}
cd frontend && npm ci && npm run dev
```
````

`exec` takes an optional `timeout=<seconds>` (1–3600, default 120), as in
`{.bash exec timeout=1200}`. Only `.bash` blocks run; `.sh`, `.shell` and `.console`
blocks can only be `skip`.

**Refused**, with the file and line:

| Written as | Why |
|---|---|
| `` ```bash `` | untagged |
| `` ```bash exec `` | without braces the site renders the block as a paragraph of text |
| `` ```{bash exec} `` | no dot: the site shows it unhighlighted |
| `` ```{.bash exec} trailing `` | text after `}` breaks the block on the site |
| `` ```{.bash exec skip} `` | both tags, or neither |
| `` ```{.bash skip} `` | `skip` without a `reason` |
| `` ```{.bash exec title="x"} `` | any other attribute (none are allowed yet) |

Blocks in other languages (`json`, `python`, `javascript`, …) aren't run and need no tag.

---

## Saying what the reader should see

Put one `expect` line per value directly under the block, with no blank line between,
and also say the value in the prose, because the reader never sees the `expect` line:

````markdown
```{.bash exec}
curl -s localhost:8000/health/ready | jq .status
```
<!-- expect: "healthy" -->

It prints `"healthy"`.
````

When the examples run, `TEXT` will have to appear in what the block prints (stdout), in
the order the lines are given, and a match can't start or end inside a word: `"active"`
doesn't match `"inactive"`, and `1` doesn't match `10`. A block that prints something
will need at least one `expect` line.

Choose a value that would be **different if the step had failed**. `curl -s` exits 0 on
a `404` or a `422`, so an example that doesn't check its output passes when it's broken.

`expect` lines don't show on the site or on GitHub.

---

## Writing a block that runs as written

- **No placeholders.** A reader can't run `your-api-key` or `flag-uuid-here`. Capture the
  value in an earlier block (`KEY=$(curl … | jq -r .key)`), or mark the block `skip`.
- **The page's blocks share one shell, top to bottom.** A variable set in one block is
  there in the next. Nothing from your own environment will be.
- **No `#` comments in a shell block.** macOS's default `zsh` doesn't treat `#` as a
  comment when you paste, so `jq .status   # "healthy"` fails with
  `Could not open file #`. Say the expected value in the prose instead. A `#` inside
  quotes, in the middle of a word (`$#`, `${#x}`, a URL's `#anchor`) or inside a
  here-document is not a comment and is fine.
- **Trailing slashes are real.** `POST /api/v1/feature-flags/` needs the slash; without it
  the API answers `307`, `curl` doesn't follow it, and nothing is printed.
- **Refused because they hide a failure:** `export X=$(command)` (and `declare`, `local`,
  `readonly`), which reports success even when the command fails — assign first, then
  export; and a last line ending in `\`, which would swallow what follows.
- **Shapes that fail when the page is right**, under `set -euo pipefail`:
  `yes | head -1` and `… | grep -q x` (exit 141 when the pipe closes early).
- **Shapes that will pass when the page is wrong:** a failure in the middle of `a && b`.
  An `expect` line catches it.

Every block that runs must also pass `bash -n`.

---

## Environments

| Environment | What will be true before the page runs |
|---|---|
| `bare` | Docker is available and nothing is running. The page starts its own stack. |
| `stack` | The Quick Start's `docker compose up -d --wait` has already run. |
| `local` | Reserved for the demo applications, and refused as not implemented yet. |

A `stack` page is coupled to the Quick Start by assertion: the Quick Start must be
enrolled as `bare` and contain exactly one block that runs
`docker compose up -d --wait`, or the check fails.

### How a run will stay away from your own stack

When pages run, each page will run under its own compose project
(`COMPOSE_PROJECT_NAME=docex-…`), so both the runner's clean-up and a page's own
`docker compose down -v` can reach only that project's containers and volumes, never
the `experimently` project a developer runs. That only holds while a page cannot reach
past its project, so the check refuses a block that:

- mentions `COMPOSE_PROJECT_NAME`, or unsets a `COMPOSE_` setting;
- passes `-p` or `--project-name` to `docker compose`;
- runs `env -u` or `env -i`;
- removes Docker resources directly (`docker rm`, `docker volume rm`, `… prune`).

A plain `docker compose down -v` is allowed: under the page's own project it removes only
what the run created. The runner will also compare `docker volume ls` before and after
a run and fail if any volume that existed before is gone. That is a detection, not a
prevention: it reports a loss, it can't undo one. Running pages locally also rebuilds and
retags the local `experimently-api:core` and `experimently-web:core` images from your
working tree, so your next `docker compose up` recreates its containers from them.

---

## Checking a page locally

```{.bash skip reason="checks the documentation itself"}
python scripts/doc_examples.py --check
```

For the render check, build the site with the site's own toolchain first:

```{.bash skip reason="builds the documentation site"}
bash scripts/docs_toolchain.sh && mkdocs build && python scripts/doc_examples.py --render site
```

---

## When the check fails

Every refusal names the page and the line of the block, and says what to change:

```text
refused: docs/getting-started/quick-start.md:44: untagged shell fence '```bash'; tag it {.bash exec} or {.bash skip reason="..."}
```

---

## Enrolling a page

1. Tag every shell block `exec` or `skip`.
2. Add `expect` lines, and say the same values in the prose.
3. Run `python scripts/doc_examples.py --check`, and copy the counts it prints into the
   page's entry in `scripts/doc_examples.toml`.
