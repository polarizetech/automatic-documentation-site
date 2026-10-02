# `docs-site.toml`

One file at the root of the repository it documents. Every section is optional; unknown
sections are an error, so a typo is caught instead of ignored.

## `[site]`

| Key | Default | Meaning |
|---|---|---|
| `name` | folder name | The short name: brand word, page titles. |
| `title` | `name` | Home-page headline. |
| `kicker` | `name` | The small label above the headline. |
| `tagline` | empty | Home-page lead. Inline Markdown. |
| `repo` | none | `owner/name` on GitHub, for source links and the header icon. |
| `branch` | `main` | The branch source links point at. |
| `private` | `false` | `true` adds the PRIVATE flag and `noindex`, and **refuses GitHub Pages**. `docsite init` sets it from the repository's visibility, and to `true` when it cannot ask. |
| `polarize_ui` | `v0.5.15` | The polarize-ui release to build against. |

## `[guides]` and `[[guide]]`: Markdown

```toml
[guides]
include = ["README.md", "docs/**/*.md"]     # the default
exclude = ["**/CLAUDE.md"]

[[guide]]                                    # name one to set its title, slug, group or order
file = "docs/EXTENSIONS.md"
title = "The extension contract"
slug = "contract"
group = "Introduction"
lead = "One line under the title."
```

Named guides come first, in the order written. A page's group is its top folder
(`docs/x.md` → "Docs"); root files are "Introduction". Links between included files become
links between pages; links to other files point at GitHub; local images are copied into the
site. Raw HTML in Markdown is shown as text, never rendered.

## `[[source]]`: an API reference

```toml
[[source]]
path = "src/mylib"        # a package directory, or one file
language = "python"       # python | typescript | javascript | swift | auto
name = "mylib"            # the import name; prefixes every documented symbol
slug = "api"              # page file name (default: from name)
title = "mylib"
group = "Reference"       # nav group
lead = "One line under the title."
exclude = ["*_pb2.py"]
recursive = true        # false: only the modules directly in `path` (a folder of loose scripts)
```

| Language | What is documented | How |
|---|---|---|
| Python | top-level functions and classes; `__all__` is honoured; names starting `_` are skipped | `ast`: exact signatures, docstrings, line numbers |
| TypeScript / JavaScript | `export`ed functions, consts, classes, interfaces, types, enums | declaration scan + the `/** */` comment above |
| Swift | `public` / `open` declarations | declaration scan + `///` comments above |

The scans for TypeScript and Swift read declarations, not types they cannot see on the
declaration line. Nothing is imported or executed for any language.

## `[catalogue]`: one page per entry

```toml
[catalogue]
file = "extensions/catalog.json"
list = "extensions"                 # the key holding the list
group = "Extensions"
strip_prefix = "mylib-ext-"          # removed from names for titles and slugs
slug_prefix = "ext-"
source = "{path}/{import}"          # where an entry's code is; formatted with the entry's fields
language = "python"
uses_prefix = "mylib"                # list what each entry imports from this package
install = 'pip install "git+https://github.com/{repo}#subdirectory={path}"'
children_title = "Kinds"     # heading for plugin pages nested under an entry

[catalogue.fields]                  # which entry keys mean what (defaults shown)
name = "name"; version = "version"; summary = "job"
repo = "location.repo"; path = "location.path"; import = "import"
requires = "requires"; boundary = "claim_boundary"; uses = "uses"
```

An entry whose `repo` is another repository gets a page from the catalogue alone, with a
callout saying where its code is.

## `[stories]`, `[[story]]`, `[hero]`, `[datasets.*]`

See [STORIES.md](STORIES.md).

```toml
[stories]
dir = "docs-site/stories"
python = ".venv/bin/python"     # falls back to the interpreter running the build (CI)
path = ["src"]                  # extra import paths, relative to the repository
plugin = "docs-site/pages.py"

[[story]]                       # any language: a command that prints a view as JSON
id = "fit"; title = "Fit a line"; page = "api"
command = "node docs-site/stories/fit.mjs"
file = "docs-site/stories/fit.mjs"

[hero]
code = "docs-site/hero.py"; run = true; note = "Captured at build time."

[datasets.mitdb]
title = "MIT-BIH Arrhythmia Database"; short = "MIT-BIH"; provider = "PhysioNet"
version = "1.0.0"; license = "ODC-By 1.0"; license_url = "..."; url = "..."
doi = "10.13026/C2F305"; cite = "..."; why = "..."; modality = "..."
```
