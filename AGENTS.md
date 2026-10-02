# CLAUDE.md — automatic-documentation-site

A docs site for any repository, generated from what the repository already says about itself.
`docsite init / build / sync / serve`, plus the shared GitHub workflow every onboarded
repository calls.

**When handed a repository to document, follow [`docs/ONBOARDING.md`](docs/ONBOARDING.md).**

## ⛔ This repository is PUBLIC

Onboarded repositories are often private. Nothing from them comes back here: no excerpt, file
name, finding or dataset in a test, fixture, example, issue or commit message. Fixtures are
invented (`tests/test_build.py`). The host's list of private repositories is local
configuration (`~/.config/automatic-documentation-site/hosts.toml`), never committed.

## Rules

1. **Stdlib only** (`dependencies = []`). The builder runs in any CI job and inside any
   repository's interpreter; a dependency here can clash with theirs.
2. **Reading is not running.** Source readers parse; they never import or execute. Only
   stories, a page plugin and the hero snippet run repository code, in `runner.py`, in a
   subprocess under the repository's interpreter.
3. **No CSS or JS here.** The page layer is polarize-ui's docs layer (`docs.css`, `docs.js`),
   fetched at a pinned release (`polarize_ui.py`). A look-and-feel change belongs in
   polarize-ui, released, then pinned. `html.py` writes markup for its classes.
4. **A failure is shown, never dropped**: a failed story on its page, a build problem on the
   home page. Do not add a code path that skips one silently.
5. **Private stays private.** `private = true` (and unknown visibility) must keep refusing
   GitHub Pages in both the CLI and the workflow. A test asserts it.
6. **Everything written into HTML is escaped.** Markdown raw HTML renders as text; link
   schemes other than http(s) and mailto are dropped.
7. **Releases:** `__version__`, `DOCSITE_REF` in the shared workflow and the tag move
   together (`tests/test_build.py::test_release_numbers_agree`). Onboarded repositories pin
   the tag, so a tag is never moved.

## Layout

| | |
|---|---|
| `src/autodocsite/config.py` | `docs-site.toml` loader; `detect()` / `propose()` for `init` |
| `src/autodocsite/readers/source.py` | Python (`ast`), TypeScript/JavaScript and Swift readers |
| `src/autodocsite/build.py` | pages, nav, search index, the page shell |
| `src/autodocsite/story.py` | the story decorator and plot-spec helpers (importable by stories) |
| `src/autodocsite/runner.py` | runs stories and plugins in the repository's interpreter |
| `src/autodocsite/html.py` | component helpers (importable by page plugins) |
| `src/autodocsite/host.py` | `sync` / `serve` for the tailnet host |
| `.github/workflows/docs-site.yml` | the shared workflow (`workflow_call`) |

Tests: `pytest` (no network; polarize-ui is faked).
