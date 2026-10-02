"""End-to-end: build small fixture repositories and read the pages back. No network.

polarize-ui is faked (POLARIZE_UI points at a folder holding empty files of the right names):
these tests are about what the builder writes, not about the design.
"""
import json
import re
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest

from autodocsite import __version__, mdlite, polarize_ui
from autodocsite.build import build
from autodocsite.cli import WORKFLOW, main
from autodocsite.config import detect, propose

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def fake_polarize_ui(tmp_path, monkeypatch):
    ui = tmp_path / "_polarize-ui"
    (ui / "fonts").mkdir(parents=True)
    for f in polarize_ui.FILES:
        (ui / f).write_text("")
    (ui / "fonts" / "inter.woff2").write_text("")
    monkeypatch.setenv("POLARIZE_UI", str(ui))


def repo(tmp_path, files: dict, toml: str) -> Path:
    r = tmp_path / "repo"
    for name, body in files.items():
        p = r / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body))
    (r / "docs-site.toml").write_text(textwrap.dedent(toml))
    return r


def page(r: Path, name: str) -> str:
    return (r / "docs-site" / "dist" / name).read_text()


def test_text_only_repository(tmp_path):
    r = repo(tmp_path, {
        "README.md": "# Protocol\n\nSee [the rules](docs/rules.md#scope) and ![fig](docs/fig.png).\n\n<script>alert(1)</script>\n",
        "docs/rules.md": "# The rules\n\n## Scope\n\n1. First\n2. Second\n\n| a | b |\n|---|---|\n| 1 | 2 |\n",
        "docs/fig.png": "png",
    }, '[site]\nname = "proto"\nrepo = "o/proto"\n')
    rep = build(r)
    assert rep["pages"] == 3 and rep["stories"] == 0 and not rep["problems"]
    readme = page(r, "readme.html")
    assert 'href="docs-rules.html#scope"' in readme            # a link between guides becomes a link between pages
    assert re.search(r'src="assets/img/[0-9a-f]{8}-fig\.png"', readme)  # the image was copied into the site
    assert "<script>alert(1)</script>" not in readme            # Markdown can never inject markup
    assert "&lt;script&gt;" in readme
    rules = page(r, "docs-rules.html")
    assert "<ol><li>First</li>" in rules and "<table>" in rules
    assert 'href="https://github.com/o/proto/blob/main/docs/rules.md"' in rules
    assert "noindex" not in page(r, "index.html")               # public by default only when the config says nothing private
    search = json.loads(page(r, "assets/search.json"))
    assert {"The rules", "Scope"} <= {s["t"] for s in search}


def test_python_source_is_read_without_importing(tmp_path):
    r = repo(tmp_path, {
        "README.md": "# lib\n",
        "src/lib/__init__.py": '"""The package overview."""\nraise RuntimeError("must never be imported")\n',
        "src/lib/core.py": '''
            """Core maths."""
            __all__ = ["add", "Point"]

            def add(a: int, b: int = 2) -> int:
                """Add two numbers.

                The long part.
                """

            def hidden():
                """Not in __all__."""

            class Point:
                """A point."""
                x: float
                y: float
            ''',
    }, '[site]\nname = "lib"\nrepo = "o/lib"\n[[source]]\npath = "src/lib"\nlanguage = "python"\nname = "lib"\nslug = "api"\n')
    build(r)
    api = page(r, "api.html")
    assert "The package overview." in api
    assert "add(a: int, b: int=2) -&gt; int" in api and "class Point" in api and "x: float" in api
    assert "api-lib-core-hidden" not in api                    # not in __all__: not public
    assert 'id="api-lib-core-add"' in api and "src/lib/core.py#L5" in api


def test_typescript_and_swift_are_read(tmp_path):
    r = repo(tmp_path, {
        "README.md": "# multi\n",
        "web/src/fit.ts": """
            /** Fit a line to points.
             *  Returns the slope. */
            export function linearFit(points: Pair[], level = 0.95): LinearFit {
              return 1
            }
            export type Pair = [number, number]
            function internal() {}
            """,
        "App/Recorder.swift": """
            /// Records the magnetometer.
            public final class Recorder {
                /// Start recording at a rate.
                public func start(rate: Double) -> Bool { true }
                func helper() {}
            }
            """,
    }, '''
        [site]
        name = "multi"
        [[source]]
        path = "web/src"
        language = "typescript"
        name = "web"
        [[source]]
        path = "App"
        language = "swift"
        name = "App"
        ''')
    build(r)
    ts, sw = page(r, "web.html"), page(r, "app.html")
    assert "function linearFit(points: Pair[], level = 0.95): LinearFit" in ts and "Fit a line to points." in ts
    assert "type Pair" in ts and "internal" not in ts
    assert "public final class Recorder" in sw and "Records the magnetometer." in sw
    assert "public func start(rate: Double) -&gt; Bool" in sw and "helper" not in sw


def test_catalogue_gives_a_page_per_entry(tmp_path):
    r = repo(tmp_path, {
        "README.md": "# cat\n",
        "ext/catalog.json": json.dumps({"extensions": [
            {"name": "x-ext-alpha", "version": "0.1.0", "job": "Does alpha.", "import": "alpha",
             "location": {"repo": "o/cat", "path": "ext/alpha"}},
            {"name": "x-ext-beta", "version": "0.2.0", "job": "Does beta.", "import": "beta",
             "location": {"repo": "o/elsewhere", "path": "tools/beta"}, "uses": ["x.core.f"]},
        ]}),
        "ext/alpha/alpha/__init__.py": '"""Alpha, the package."""\n',
        "ext/alpha/alpha/run.py": 'def go():\n    """Go."""\n',
    }, '''
        [site]
        name = "cat"
        repo = "o/cat"
        [catalogue]
        file = "ext/catalog.json"
        list = "extensions"
        group = "Extensions"
        strip_prefix = "x-ext-"
        slug_prefix = "ext-"
        source = "{path}/{import}"
        language = "python"
        ''')
    build(r)
    alpha, beta = page(r, "ext-alpha.html"), page(r, "ext-beta.html")
    assert "Alpha, the package." in alpha and 'id="api-alpha-run-go"' in alpha
    assert "Lives in another repository" in beta and "o/elsewhere" in beta and "x.core.f" in beta
    assert "ext-alpha.html" in page(r, "index.html")


def test_stories_run_and_a_failure_is_shown_not_dropped(tmp_path):
    r = repo(tmp_path, {
        "README.md": "# s\n",
        "lib.py": 'def double(x):\n    """Twice x."""\n    return 2 * x\n',
        "docs-site/stories/lib.py": '''
            from autodocsite.story import story, table, view

            @story(id="doubles", title="Double a number", summary="It doubles.", page="lib", dataset="synth", calls=("lib.double",))
            def doubles():
                import lib
                result = lib.double(21)
                return view(output=[table("result", ["x"], [[result]])], facts=[("answer", result)])

            @story(id="breaks", title="A story that raises", summary="It fails.", page="lib")
            def breaks():
                raise ValueError("deliberate")
            ''',
        "docs-site/stories/cmd.py": 'import json\nprint(json.dumps({"output": [{"type": "table", "title": "t", "columns": ["a"], "rows": [["1"]]}], "input": [], "facts": [], "raw": None}))\n',
    }, f'''
        [site]
        name = "s"
        [[source]]
        path = "lib.py"
        language = "python"
        name = "lib"
        slug = "lib"
        [stories]
        dir = "docs-site/stories"
        python = "{sys.executable}"
        path = ["."]
        [[story]]
        id = "from-command"
        title = "Any language"
        page = "lib"
        command = "{sys.executable} docs-site/stories/cmd.py"
        file = "docs-site/stories/cmd.py"
        [datasets.synth]
        title = "Synthetic"
        short = "Synthetic"
        license = "CC0"
        ''')
    rep = build(r)
    assert rep["stories"] == 3 and rep["stories_ok"] == 2
    lib = page(r, "lib.html")
    # the story file is named like the module it demonstrates: `import lib` must find the MODULE
    assert "result = lib.double(21)" in lib and "return view(" not in lib
    assert "&quot;42&quot;" in lib or '"42"' in lib.replace("&quot;", '"')
    assert "Story failed" in lib and "ValueError: deliberate" in lib
    assert 'id="story-from-command"' in lib
    assert 'href="lib.html#api-lib-double"' in lib               # `calls` link to the API reference
    assert "Synthetic" in page(r, "datasets.html") and "CC0" in lib
    # an unchanged story is served from cache on the next build
    rep2 = build(r)
    assert rep2["stories_ok"] == 2


def test_private_site_is_marked_and_refused_for_pages(tmp_path, capsys):
    r = repo(tmp_path, {"README.md": "# p\n"}, '[site]\nname = "p"\nprivate = true\n')
    build(r)
    idx = page(r, "index.html")
    assert 'content="noindex, nofollow"' in idx and "ui-docsite__flag" in idx
    with pytest.raises(SystemExit) as ex:
        main(["build", str(r), "--publish", "pages"])
    assert "never published to GitHub Pages" in str(ex.value)


def test_init_proposes_a_config_that_loads(tmp_path):
    r = repo(tmp_path, {
        "README.md": "# found\n\nA tool that does a thing.\n",
        "src/found/__init__.py": "",
        "src/found/a.py": "def f():\n    pass\n",
        "plugins/catalog.json": json.dumps({"plugins": [{"name": "one", "version": "1"}]}),
        "docs/guide.md": "# Guide\n",
    }, "")
    (r / "docs-site.toml").unlink()
    found = detect(r)
    assert found["private"] is None                               # no remote: unknown, so treated as private
    text = propose(found)
    cfg = tomllib.loads(text)
    assert cfg["site"]["private"] is True
    assert cfg["source"][0]["path"] == "src/found" and cfg["catalogue"]["list"] == "plugins"
    assert "docs/**/*.md" in cfg["guides"]["include"]
    assert main(["init", str(r), "--write"]) == 0
    wf = (r / ".github/workflows/docs-site.yml").read_text()
    assert "publish: branch" in wf and "contents: write" in wf
    assert "docs-site/dist/" in (r / ".gitignore").read_text()
    build(r)
    assert "A tool that does a thing." in page(r, "index.html")


def test_release_numbers_agree():
    wf = (ROOT / ".github/workflows/docs-site.yml").read_text()
    assert f"DOCSITE_REF: v{__version__}" in wf
    assert "docs-site.yml@v{version}" in WORKFLOW


def test_markdown_never_injects_markup():
    out = mdlite.render('**b** `<i>` <img src=x onerror=alert(1)>\n\n[x](javascript:alert(1))')
    assert "<img src=x" not in out and "&lt;img" in out
    assert "<strong>b</strong>" in out and "<code>&lt;i&gt;</code>" in out
    assert "javascript:" not in out and '<a href="#">x</a>' in out
