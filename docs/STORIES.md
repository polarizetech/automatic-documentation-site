# Stories

A story is **one real call on one dataset**, shown three ways from one function so they cannot
disagree: the code (the function's own source), the input, and the output computed at build
time. It is the docs equivalent of a Storybook story.

## A Python story

`docs-site/stories/fit.py`:

```python
import numpy as np
import datasets as D                       # a helper module beside the stories
from autodocsite.story import story, view, trace, table

@story(id="fit-line", title="Fit a line", page="api", dataset="synthetic",
       summary="Forty points around a known slope.", calls=("mylib.fit",))
def fit_line():
    import mylib

    x, y = D.points()
    result = mylib.fit(x, y)

    return view(input=[trace("points", y, fs=4.0)],
                output=[table("fit", ["slope", "r2"], [[result.slope, result.r2]])],
                facts=[("slope", f"{result.slope:.3f}")], raw=result)
```

- **The body is the example.** Everything except the final `return view(...)` is shown, with
  the module's imports that the body uses prepended.
- `page` is the slug of the page it appears on: a `[[source]]` slug, a catalogue entry's slug,
  or a plugin page's slug.
- `calls` are linked to the API reference.
- `badge` (default `MEASURED`) is the evidence tier on the output. Use `PREDICTED` or
  `MODELLED` for a simulation, and `badge=None` for synthetic data that measures nothing.
- A story file may be named after the package it demonstrates (`stories/mylib.py`): the
  repository's own packages are found first.

Stories run in a subprocess under `[stories] python`, so they can import anything the
repository can. Results are cached in `docs-site/.cache`, keyed on the story file's source and
the repository's commit; a failure is never cached.

## Stories that call a live service

A story that asks an outside service (a public catalogue, an API) will sometimes find it down.
That is not a failure of the code the story shows, and it must not look like one:

```python
from autodocsite.story import service, story, view, table

@story(id="search", title="Search the catalogue", page="api", summary="...")
def search():
    import mylib

    with service("OpenNeuro"):                 # a transport failure in here becomes Unavailable
        refs = mylib.search("openneuro", modality="eeg")

    return view(output=[table("refs", ["id"], [[r.id] for r in refs])])
```

`service(...)` converts only transport failures (timeouts, refused connections, DNS, TLS,
HTTP-client errors). Anything else still fails the story. You can also `raise Unavailable(...)`
yourself.

When a service does not answer, the page says so, shows the story's **last successful
result with its date**, and the build does not count it as a failure (`--strict` included).
The last result comes from the story cache, which the workflow keeps between runs.
"Unavailable" never means "nothing exists".

A story may sit on any page, a Markdown guide included: set `page` to that page's slug.

## A story in any other language

```toml
[[story]]
id = "fit"; title = "Fit a line"; page = "api"; dataset = "synthetic"
command = "node docs-site/stories/fit.mjs"
file = "docs-site/stories/fit.mjs"      # shown as the code
```

The command prints one JSON object to stdout:

```json
{"input": [spec, ...], "output": [spec, ...], "facts": [["label", "value"]], "raw": null}
```

## Plot specs

A spec is plain JSON, drawn by polarize-ui's `docs.js` (typed in its `docs.d.ts`):

| `type` | Fields |
|---|---|
| `line` | `title, series:[{name, x:[], y:[]}], xlabel, ylabel, markers:[{x, label}], stack?, caption?` |
| `stems` | `title, groups:[{name, lines:[{x, y}], invert?, flags?, note?}], xmax?` |
| `bars` | `title, items:[{label, value}]` |
| `table` | `title, columns:[], rows:[[]]` |
| `verdicts` | `title, items:[{key, verdict, reason?, meta?, tone?}]` |

The helpers in `autodocsite.story` (`trace`, `line`, `spectrum`, `stems`, `bars`, `table`,
`verdicts`) build these and decimate long traces for display.

## The rules

1. **Data is public and licensed, or synthetic.** Never a recording of a person made by the
   project, never unpublished data. Register every dataset in `[datasets.*]` with its provider,
   version, licence, DOI and citation; stories name it by key, so the chip and the Datasets
   page cannot drift from the data.
2. **Prefer data where the answer is known in advance** (a tagged stimulus, a textbook signal,
   a synthetic truth). The story is then a check as well as a demonstration.
3. **A failing story stays on the page**, labelled, with its traceback.
4. **A verdict is a word** (`present`, `absent`, `unavailable`); colour only reinforces it.
5. **No story is better than an invented one.** A page with nothing to demonstrate says so.

## Custom pages

`[stories] plugin = "docs-site/pages.py"` names a module with `pages(ctx) -> list[dict]`, run
in the repository's interpreter. Each dict is a page:

```python
from autodocsite.html import STORIES, chip, chips, h2, table, callout, api, tier

def pages(ctx):
    return [{
        "slug": "kind-fast", "title": "Fast kind", "nav": "Fast kind",
        "parent": "ext-plotting",     # nest under that page in the nav
        "eyebrow": "kind", "lead": "One line.", "card": "Shown on the parent's card.",
        "html": chips(chip("rate", "<code>1.2 Hz</code>")) + h2("overview", "Overview") + STORIES,
        "toc": [(2, "overview", "Overview"), (2, "stories", "Stories")],
        "search": [{"t": "Fast kind", "s": "Kind", "k": "Kind"}],
    }]
```

`STORIES` marks where that page's stories go. `api("pkg.mod.fn")` becomes a link to the API
reference when it documents that name.
