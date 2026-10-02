# automatic-documentation-site

A docs site for any repository, generated from what the repository already says about itself.
Nothing on a generated page is typed in by hand: every page names its source, and a wrong page
is fixed by fixing that source.

It works for a Python library, a TypeScript or Swift codebase, and a repository that is only
text. The look is [polarize-ui](https://github.com/polarizetech/polarize-ui)'s docs layer; this
repository holds the tooling and no CSS.

```bash
pip install "git+https://github.com/polarizetech/automatic-documentation-site@v0.2.1"

docsite init path/to/repo --write    # look at the repository; write docs-site.toml and the workflow
docsite dev path/to/repo             # build, open the browser, rebuild and reload as you edit
docsite build path/to/repo           # → path/to/repo/docs-site/dist
```

`docsite dev` is the everyday command, the way `storybook dev` is for components. It serves on
your own machine only.

**A built site needs no server.** It is a folder of plain files: open `docs-site/dist/index.html`
and search, plots and navigation all work. There is nothing to host unless you want to.

## What a site is made from

| In the repository | On the site | Reader |
|---|---|---|
| `README.md`, `docs/**/*.md`, any Markdown you name | guide pages, grouped by folder | `[guides]` |
| a source tree | an API reference: public functions, classes and types, read **without importing or running anything** | `[[source]]`: Python (exact, by `ast`), TypeScript/JavaScript and Swift (exported or public declarations and their doc comments) |
| a JSON catalogue of extensions, providers, plugins or domains | one page per entry, with its own API reference | `[catalogue]` |
| small example files | **stories**: one real call each, run at build time, shown with its code, input and output | `[stories]` (Python) or `[[story]]` (a command in any language) |
| a dataset registry | a Datasets page; a licence chip on every story that uses one | `[datasets.*]` |
| things only this repository has | custom pages, written with the same components | a page plugin |

A repository with no code needs only `[site]`: its Markdown becomes the site.

## How a repository stays up to date

`docsite init --write` installs a small workflow in the repository. On every push to its
default branch it calls the shared workflow here, which rebuilds the site and publishes it:

| Repository | Published to | Read it with |
|---|---|---|
| public | GitHub Pages | its Pages URL |
| **private** | a `docs-site` branch in the same private repository. Nothing leaves it. | `docsite open owner/name`, which fetches that branch with your own git access and opens it from the folder |

A site whose config says `private = true` is refused for GitHub Pages, in the CLI and in the
workflow.

## Documentation

- [`docs/ONBOARDING.md`](docs/ONBOARDING.md): the procedure for giving an existing repository a docs site. **Start here**, human or agent.
- [`docs/CONFIG.md`](docs/CONFIG.md): every key in `docs-site.toml`.
- [`docs/STORIES.md`](docs/STORIES.md): writing stories, the data rules, custom pages.
- [`docs/WORKFLOW.md`](docs/WORKFLOW.md): the installed workflow and the shared one it calls.
- [`docs/HOSTING.md`](docs/HOSTING.md): optional. Serving several repositories' sites from one machine, for reading on other devices.

## Design

- **Stdlib only.** The builder runs in any CI job, and inside any repository's own interpreter
  (for stories), so it brings no dependency that could clash with theirs.
- **Reading is not running.** Source is parsed, never imported. Only stories, a page plugin and
  an optional hero snippet execute repository code, in a subprocess under the interpreter the
  repository names.
- **A failure is shown, not dropped.** A story that raises appears on its page as failed, with
  its traceback. A build problem is listed on the home page. `--strict` turns either into a
  failed build.
- **The design is pinned.** Each site names the polarize-ui release it builds against.
- **No server required.** polarize-ui ships its scripts as ES modules, which a browser will not
  load from a folder. The build converts them to classic scripts mechanically and embeds what
  they would fetch, so one build works from `file://`, from localhost and from a web host.

polarize-ui itself is documented with Storybook, not with this.

MIT licensed.
