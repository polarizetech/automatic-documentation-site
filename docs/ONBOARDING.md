# Onboarding a repository

The procedure for giving an existing repository a docs site. It is written for whoever does it,
a person or a coding agent handed the repository in a session. Work through it in order. Stop
and ask the repository's owner at the points marked **ASK**.

The aim is not a large site. It is a site where **every page has a source in the repository**,
so it stays true when the code changes.

## 0. Before anything

- **Is this repository polarize-ui?** Then stop: it is documented with Storybook.
- **Is it private?** `docsite init` asks GitHub. A private repository gets `private = true`,
  which marks every page, blocks indexing, and makes GitHub Pages impossible for it. When
  visibility cannot be determined it is treated as private. Never weaken this.
- **Never copy a private repository's content into a public one**, this repository included:
  no excerpts in issues, tests, fixtures or examples here.

## 1. Look

```bash
docsite init <repo>
```

This writes nothing. It prints what it found (Markdown, source trees, catalogues) and the
`docs-site.toml` and workflow it would create. Read it against the repository:

- Is each `[[source]]` a real public API, or internal code nobody calls from outside? Drop the
  internal ones. A reference page for code with no docstrings is noise: prefer adding
  docstrings in the repository to documenting around their absence.
- Is there a list of parts the repository maintains (extensions, providers, domains, plugins,
  templates)? If it is JSON, it is a `[catalogue]`. If it lives in code, it is a page plugin.
- Which Markdown is for readers, and which is working notes (agent instructions, session
  logs, changelogs of internal work)? Exclude the notes.

## 2. Write the config

```bash
docsite init <repo> --write
```

Then edit `docs-site.toml` ([CONFIG.md](CONFIG.md)): set `title` and `tagline` from the
README's own first lines, name the guides that matter with `[[guide]]`, give each `[[source]]`
a `lead`, and map the catalogue's fields. Do not write prose here that the repository does not
already say; if a page needs an explanation, the explanation belongs in a docstring or a
Markdown file in the repository.

Read it as you edit:

```bash
docsite dev <repo>
```

It opens the browser and reloads the page whenever the config, the Markdown, the source or a
story changes.

## 3. Stories

Skip this step for a text-only repository.

For each part a new user would call first, write one story ([STORIES.md](STORIES.md)). Two or
three per package is enough.

- **ASK** which datasets may be used, unless the repository already names them. Only public,
  licensed data or synthetic data. Never a recording made by the project.
- Register each dataset in `[datasets.*]` with licence, version, DOI and citation.
- Pick data where the right answer is known beforehand.
- If a story fails because the code is wrong, **do not hide it or work around it**. Leave it
  failing on the page and report the bug to the owner.
- If nothing public can demonstrate a part, say so on its page. Do not invent a demonstration.

## 4. Things only this repository has

If something important has no reader (a registry defined in code, a taxonomy, a protocol
table), write a page plugin (`[stories] plugin`, see STORIES.md) that reads it at build time.
Keep it in the repository it documents. If two repositories need the same kind of page,
propose a reader here instead.

## 5. Check

- Cold build: `docsite build <repo> --refresh --strict`, then open `docs-site/dist/index.html` straight from the folder. Every story passes or is knowingly
  left failing.
- Read every page once, in light and dark, and at phone width.
- Search for a function by its short name.
- Follow three source links.
- For a private repository: confirm the PRIVATE flag is on every page.

## 6. Install the workflow

`docsite init --write` already created `.github/workflows/docs-site.yml`. Set `setup:` to
whatever makes the repository importable for its stories.

- Public repository: `publish: pages`. **ASK** the owner to enable GitHub Pages (source:
  GitHub Actions) in the repository settings; it cannot be done from the workflow.
- Private repository: `publish: branch`. The built site is committed to the `docs-site`
  branch of the same repository; anyone with access reads it with `docsite open owner/name`.

**ASK** before committing or pushing to the repository: pushing the workflow starts it.

## 7. Hand over

Tell the owner: what the site is generated from, which stories exist and which fail and why,
what has no page yet and what it would take, and where the site is published.
