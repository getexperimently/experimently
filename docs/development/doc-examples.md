# Runnable Documentation Examples

The shell examples on an enrolled page are run in CI exactly as they're written, in one
shell session per page, against a real stack. `scripts/doc_examples.py` does it on every
pull request (the `doc-examples` workflow). A page fails when:

- a command fails;
- an example stops printing what the page says it prints;
- a shell block is left untagged, or tagged in a form the site would break;
- a block contains something a reader can't paste as written;
- the counts of blocks and expectations stop matching the enrolment file;
- a tagged block renders as a paragraph instead of code.

---

## Which pages are checked

Every Markdown page in the repository, except `CLAUDE.md` files and anything under
`.claude/`. The check walks the tree for them (skipping `node_modules`, `venv`, `site`
and hidden directories other than `.github`), and the list it finds must equal
`[meta] universe` in `scripts/doc_examples.toml` exactly. A new page, or a renamed one,
fails the check until the list says so.

On every one of those pages:

- every code fence names a language (use `text` for output, a directory tree or
  anything else that is not code);
- a shell fence is `bash`; `sh`, `shell`, `console`, `zsh`, `sh-session`,
  `shell-session`, `fish`, `powershell`, `ps1` and the like are refused, because
  nothing would check what they contain;
- a page with a `bash` block is exactly one of **enrolled**, **exempt** or **pending**.

Pending is the rollout, and it only shrinks: the list of pending pages was frozen in
`scripts/doc_examples.py` when the walk landed, so a page can leave it but not join
it. Each pending page records what is left to fix on it (its shell comment lines,
unlabelled fences and blocks that fail `bash -n`), exactly, and each number can only
fall.

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

On an enrolled page, every `bash` block carries exactly one tag, in braces.

**Run it:**

````markdown
```{.bash exec}
curl -s localhost:8000/health/ready | jq .status
```
````

**Don't run it, and say why.** The reason is required, and it starts with a category
(see [Pages that cannot run here](#pages-that-cannot-run-here)). It's visible to anyone
reading the page source, so write it for them:

````markdown
```{.bash skip reason="server: starts a long-running development server"}
cd frontend && npm ci && npm run dev
```
````

`exec` takes an optional `timeout=<seconds>` (1–3600, default 120), as in
`{.bash exec timeout=1200}`.

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
| `` ```{.bash skip reason="needs AWS"} `` | the reason names no category |
| `` ```zsh `` | a shell the runner doesn't know (on every page, enrolled or not) |
| ` ``` ` with no language | on every page; use `text` for output |
| a block indented four spaces | on every page: it renders as code but names no language; fence it |

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

`TEXT` has to appear in what the block prints (stdout), in the order the lines are
given, and a match can't start or end inside a word: `"active"` doesn't match
`"inactive"`, and `1` doesn't match `10`. A block that prints something needs at least
one `expect` line. The one exception is the Quick Start's `docker compose up -d --wait`:
when it has to build the images it prints the build log, and when they exist it prints
nothing, so it's checked by its exit status (`--wait` fails unless every service is
healthy) and by the next block's expectations.

Choose a value that would be **different if the step had failed**. `curl -s` exits 0 on
a `404` or a `422`, so an example that doesn't check its output passes when it's broken.

`expect` lines don't show on the site or on GitHub.

---

## Writing a block that runs as written

- **No placeholders.** A reader can't run `your-api-key` or `flag-uuid-here`. Capture the
  value in an earlier block (`KEY=$(curl … | jq -r .key)`), or mark the block `skip`.
- **The page's blocks share one shell, top to bottom.** A variable set in one block is
  there in the next. Nothing from your own environment is: each page runs with only
  `PATH`, `HOME`, `USER`, `TMPDIR` and Docker's own settings.
- **No `#` comments in a shell block**, `skip` blocks included (see
  [Rewriting a comment](#rewriting-a-comment)).
- **Trailing slashes are real.** `POST /api/v1/feature-flags/` needs the slash; without it
  the API answers `307`, `curl` doesn't follow it, and nothing is printed.
- **Refused because they hide a failure:** `export X=$(command)` (and `declare`, `local`,
  `readonly`), which reports success even when the command fails — assign first, then
  export; and a last line ending in `\`, which would swallow what follows.
- **Shapes that fail when the page is right**, under `set -euo pipefail`:
  `yes | head -1` and `… | grep -q x` (exit 141 when the pipe closes early).
- **Shapes that pass when the page is wrong:** a failure in the middle of `a && b`.
  An `expect` line catches it.
- **Nothing is installed, and no cloud account is reached.** A block that runs may not
  call a package manager (`pip`, `pipx`, `poetry`, `uv`, `npm`, `npx`, `yarn`, `pnpm`,
  `bun`, `gem`, `composer`, `go get|install|run`, `cargo install`, `mvn`, `gradle`,
  `swift package|build`, `dotnet add|restore|build`): our package names aren't
  published yet, so a run would fetch whatever else holds the name. Nor may it call
  `aws`, `cdk` or `sam`. Writing `\aws`, `"aws"` or `/usr/local/bin/aws` is the same
  command. Text inside a here-document is data and is not checked for either. Tag
  such a block `skip` with the `registry` or `aws` category.

Every block, `exec` or `skip`, must also pass `bash -n` (with bash 4.4 or later, the one
that runs the examples; macOS's `/bin/bash` is 3.2 and is refused). A `skip` block whose
reason is `fragment: …` is not syntax-checked, since it is a template to fill in; if it
isn't shell at all, label it `text` instead.

---

## Pages that cannot run here

A `skip` reason starts with one of these categories, then `: ` and the words a reader
of the source will see:

| Category | The block… |
|---|---|
| `checkout` | clones or enters the repository (the runner is already inside one) |
| `dev` | is a contributor's command in a development checkout (venv, make, pytest, this repository's own tooling) |
| `server` | starts a long-running process |
| `aws` | needs an AWS account or credentials |
| `idp` | needs an identity-provider tenant (Cognito, SAML, OIDC) |
| `secret` | needs a credential or third-party account the reader holds |
| `registry` | installs a package from a public registry; it must name the package manager |
| `toolchain` | needs a language toolchain the runner doesn't use (Go, .NET, JVM, Swift, …) |
| `destructive` | changes state a reader must choose to change (restore, rollback, delete) |
| `demo` | needs the demo applications |
| `fragment` | is a template to fill in, not runnable as written |
| `bug #N` | fails because of the product defect in issue N: `bug #123: …` |

The check prints how many skipped blocks each category holds.

---

## Rewriting a comment

macOS's default `zsh` doesn't treat `#` as a comment when you paste, so
`jq .status   # "healthy"` fails with `Could not open file #`, and a whole-line
`# step 2` fails with `command not found: #`. Worse, `ENV=prod   # or staging` fails
silently and leaves `ENV` at whatever it was before. Say it in the sentence before or
after the block instead:

````markdown
Set the environment you are rolling back (`prod` or `staging`):

```{.bash skip reason="aws: rolls back a deployment"}
ENV=prod
```
````

A `#` inside quotes, in the middle of a word (`$#`, `${#x}`, a URL's `#anchor`) or
inside a here-document is not a comment and is fine.

---

## Environments

| Environment | What is true before the page runs |
|---|---|
| `bare` | Docker is available and nothing is running. The page starts its own stack. |
| `stack` | The Quick Start's `docker compose up -d --wait` has already run. |
| `local` | Reserved for the demo applications, and refused as not implemented yet. |

A `stack` page is coupled to the Quick Start by assertion: the Quick Start must be
enrolled as `bare` and contain exactly one block that runs
`docker compose up -d --wait`, or the check fails.

### How a run will stay away from your own stack

Each page runs under its own compose project (`COMPOSE_PROJECT_NAME=docex-…`), so both the runner's clean-up and a page's own
`docker compose down -v` can reach only that project's containers and volumes, never
the `experimently` project a developer runs. That only holds while a page cannot reach
past its project, so the check refuses a block that:

- mentions `COMPOSE_PROJECT_NAME`, or unsets a `COMPOSE_` setting;
- passes `-p` or `--project-name` to `docker compose`;
- runs `env -u` or `env -i`;
- removes Docker resources directly (`docker rm`, `docker volume rm`, `… prune`).

A plain `docker compose down -v` is allowed: under the page's own project it removes only
what the run created. After each page the runner removes the project and fails if any of
its containers, volumes or networks remain; before a page it refuses, touching nothing,
if a port the stack publishes is in use or a previous run left `docex-` resources behind.
It also compares `docker volume ls` before and after the run and fails if any volume that
existed before is gone. That is a detection, not a
prevention: it reports a loss, it can't undo one. Running pages locally also rebuilds and
retags the local `experimently-api:core` and `experimently-web:core` images from your
working tree, so your next `docker compose up` recreates its containers from them.

---

## Checking a page locally

```{.bash skip reason="dev: checks the documentation itself"}
python scripts/doc_examples.py --check
```

To run the examples, stop anything that holds the stack's ports first (your own
`docker compose stop` is enough; your volumes are left alone). `--env` moves a port if
something else holds it, and `--only` runs one page:

```{.bash skip reason="dev: runs the documentation's examples"}
python scripts/doc_examples.py --run --only docs/feature-flags/create.md
```

For the render check, build the site with the site's own toolchain first:

```{.bash skip reason="dev: builds the documentation site"}
bash scripts/docs_toolchain.sh && mkdocs build && python scripts/doc_examples.py --render site
```

---

## When the check fails

Every problem is reported in the same run, one line each. Each names the page (and the
line, where there is one) and says what to change. In CI each line is also an
annotation on the pull request's diff. For a new page with a `zsh` block, and a comment
left in an enrolled one:

```text
refused: docs/guides/new-page.md: a page scripts/doc_examples.toml does not know. Add it to [meta] universe (docs/development/doc-examples.md#enrolling-a-page).
refused: docs/guides/new-page.md:9: 'zsh' names a shell the runner does not know; use {.bash …}
refused: docs/guides/new-page.md: 1 shell block, and the page is not enrolled. Add it to scripts/doc_examples.toml (docs/development/doc-examples.md#enrolling-a-page), or list it as exempt with a reason.
refused: docs/guides/tour.md:14: shell comment "# prints the flag's id" breaks when pasted into zsh. Move it into the sentence before or after the block (docs/development/doc-examples.md#rewriting-a-comment).
4 problems
```

---

## Enrolling a page

1. Add the page's path to `[meta] universe` if it is new.
2. Tag every shell block `exec` or `skip`, remove its comments, and give every fence a
   language.
3. Add `expect` lines, and say the same values in the prose.
4. Run `python scripts/doc_examples.py --check`, and copy the counts it prints into a
   `[[document]]` entry in `scripts/doc_examples.toml`; add its `exec` to `[meta] exec`,
   add one to `[meta] documents`, and remove the page's line from `[pending]` if it has
   one.

A page with no `bash` block needs no entry, and enrolling one is refused.

---

## Exempting a page

A page whose shell blocks are deliberately left untagged is listed as exempt, with a
reason (1–200 characters), instead of enrolled:

```toml
[[exempt]]
path = "docs/example.md"
reason = "why its blocks are not tagged"
```

An exempt page still obeys the rules for every page (languages named, no other shell)
and its `bash` blocks still carry no comments and pass `bash -n`. An exempt page with no
`bash` block is refused.
