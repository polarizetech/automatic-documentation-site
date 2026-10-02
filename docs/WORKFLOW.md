# The workflow

`docsite init --write` installs `.github/workflows/docs-site.yml` in the repository:

```yaml
name: docs-site
on:
  push:
    branches: [main]
  workflow_dispatch:
permissions:
  contents: write
jobs:
  docs:
    uses: polarizetech/automatic-documentation-site/.github/workflows/docs-site.yml@v0.2.1
    with:
      publish: branch
      setup: pip install -e .
```

It calls the shared workflow in this repository, so the build steps live in one place. A fix
here reaches a repository when it bumps the tag.

| Input | Default | |
|---|---|---|
| `publish` | `artifact` | `branch`, `pages` or `artifact` (below) |
| `setup` | none | Shell that makes the repository importable for its stories |
| `python-version` | `3.12` | |
| `strict` | `false` | Fail the job if any story fails or any problem is recorded |
| `working-directory` | `.` | Where `docs-site.toml` is |

## Where the site goes

**`branch` (private repositories).** The built site is committed to a `docs-site` branch of
the same repository, as a single commit replaced on every build. It needs
`permissions: contents: write`. A push made with the workflow's token does not start another
workflow, and the trigger is the default branch only, so it cannot loop. Read it with
`docsite open owner/name`: it fetches the branch with your own git access and opens
`index.html` from the folder. No server is involved.

**`pages` (public repositories).** Deployed to GitHub Pages. Enable Pages once, with source
"GitHub Actions", in the repository's settings. It needs `pages: write` and `id-token: write`.
**Refused when `docs-site.toml` says `private = true`.**

**`artifact`.** The site is attached to the workflow run. It is always attached for `branch`
too, so a failed publish still leaves the build.

## Stories in CI

Stories run in the job's Python after `setup`. Datasets they download are cached between runs
(`docs-site/.cache`, `~/.cache/dataset-fetch`). A story that needs data or hardware only your
machine has will fail in CI and show as failed on the page; build that repository locally
instead (`docsite build`), and set `publish: artifact` or remove the workflow.

## Releases

`DOCSITE_REF` in the shared workflow is the builder version that workflow file installs; a
test holds it to the package version, so a tag always installs itself.
