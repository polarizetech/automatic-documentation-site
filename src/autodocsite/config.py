"""docs-site.toml: what a repository's docs site is generated FROM.

The file lives at the root of the repository it documents. Every section is optional; a
repository with only Markdown needs `[site]` and nothing else (guides default to README.md and
docs/**/*.md). Full reference: docs/CONFIG.md.

    [site]
    name = "mylib"                          # short name: the brand word and page titles
    title = "What the library does, in one line."  # home-page headline
    tagline = "Reference for ..."
    repo = "owner/name"                    # for source links
    branch = "main"
    private = true                         # PRIVATE pill, noindex, never GitHub Pages
    polarize_ui = "v0.5.15"                # the design release to build against

    [guides]                               # Markdown -> pages
    include = ["README.md", "docs/**/*.md"]
    exclude = []
    [[guide]]                              # or name them, to set title/slug/order
    file = "docs/EXTENSIONS.md"; title = "The extension contract"; slug = "contract"

    [[source]]                             # a source tree -> an API reference page
    path = "src/mylib"; language = "python"; name = "mylib"; slug = "core"; title = "mylib"
    group = "Core"; lead = "..."

    [catalogue]                            # a JSON list -> one page per entry
    file = "extensions/catalog.json"; list = "extensions"; group = "Extensions"
    strip_prefix = "mylib-ext-"; slug_prefix = "ext-"
    source = "{path}/{import}"             # where an entry's code is (formatted with its fields)
    language = "python"; uses_prefix = "mylib"
    install = 'pip install "git+https://github.com/{repo}#subdirectory={path}"'
    [catalogue.fields]                     # which entry keys mean what (defaults shown)
    name = "name"; version = "version"; summary = "job"; repo = "location.repo"
    path = "location.path"; import = "import"; requires = "core_requires"
    boundary = "claim_boundary"; uses = "uses"

    [stories]
    dir = "docs-site/stories"; python = ".venv/bin/python"; path = ["src"]
    plugin = "docs-site/pages.py"          # optional: pages(ctx) -> custom pages
    [[story]]                              # a story in any language: a command printing a view
    id = "..."; title = "..."; page = "core"; command = "node docs-site/stories/x.mjs"; file = "..."

    [hero]
    code = "docs-site/hero.py"; run = true; note = "..."

    [datasets.mitdb]
    title = "..."; short = "MIT-BIH"; provider = "PhysioNet"; version = "1.0.0"
    license = "ODC-By 1.0"; license_url = "..."; url = "..."; doi = "..."; cite = "..."; why = "..."
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    tomllib = None

CONFIG_NAME = "docs-site.toml"
DEFAULT_POLARIZE_UI = "v0.5.15"

CATALOGUE_FIELDS = {"name": "name", "version": "version", "summary": "job", "repo": "location.repo",
                    "path": "location.path", "import": "import", "requires": "requires",
                    "boundary": "claim_boundary", "uses": "uses"}


@dataclass
class Config:
    root: Path
    site: dict = field(default_factory=dict)
    guides: dict = field(default_factory=dict)
    guide: list = field(default_factory=list)
    source: list = field(default_factory=list)
    catalogue: dict = field(default_factory=dict)
    stories: dict = field(default_factory=dict)
    story: list = field(default_factory=list)
    hero: dict = field(default_factory=dict)
    datasets: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.site.get("name") or self.root.name

    @property
    def repo(self) -> str:
        return self.site.get("repo", "")

    @property
    def repo_url(self) -> str:
        return f"https://github.com/{self.repo}" if self.repo else ""

    @property
    def branch(self) -> str:
        return self.site.get("branch", "main")

    @property
    def private(self) -> bool:
        return bool(self.site.get("private", False))


class ConfigError(SystemExit):
    pass


def load(root: Path) -> Config:
    root = root.resolve()
    path = root / CONFIG_NAME
    if not path.exists():
        raise ConfigError(f"{path} not found. Run `docsite init {root}` to write one.")
    if tomllib is None:
        raise ConfigError("docsite needs Python 3.11+ (tomllib) to read docs-site.toml")
    data = tomllib.loads(path.read_text())
    known = {"site", "guides", "guide", "source", "catalogue", "stories", "story", "hero", "datasets"}
    unknown = sorted(set(data) - known)
    if unknown:
        raise ConfigError(f"{path}: unknown section(s) {unknown}. Known: {sorted(known)}")
    cfg = Config(root=root, **{k: data[k] for k in known if k in data})
    for s in cfg.source:
        if "path" not in s:
            raise ConfigError(f"{path}: every [[source]] needs a `path`")
        if not (root / s["path"]).exists():
            raise ConfigError(f"{path}: [[source]] path {s['path']!r} does not exist")
    if cfg.catalogue and not (root / cfg.catalogue.get("file", "")).is_file():
        raise ConfigError(f"{path}: [catalogue] file {cfg.catalogue.get('file')!r} does not exist")
    return cfg


def dig(obj, dotted: str, default=None):
    for part in dotted.split("."):
        if not isinstance(obj, dict) or part not in obj:
            return default
        obj = obj[part]
    return obj


# ── init: look at a repository and propose a config ─────────────────────────────────────────

def _git_remote(root: Path) -> tuple[str, str]:
    import subprocess
    try:
        url = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip()
        m = re.search(r"github\.com[:/]([^/]+/[^/.]+)", url)
        head = subprocess.run(["git", "-C", str(root), "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
                              capture_output=True, text=True).stdout.strip()
        return (m.group(1) if m else ""), (head.split("/", 1)[1] if "/" in head else "main")
    except Exception:
        return "", "main"


def _visibility(repo: str) -> bool | None:
    """True if private, False if public, None if it could not be asked."""
    import subprocess
    try:
        out = subprocess.run(["gh", "repo", "view", repo, "--json", "visibility", "-q", ".visibility"],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        return {"PRIVATE": True, "INTERNAL": True, "PUBLIC": False}.get(out)
    except Exception:
        return None


def detect(root: Path) -> dict:
    """What `docsite init` found. Facts only; the proposal is written by propose()."""
    from .readers import source as S
    root = root.resolve()
    repo, branch = _git_remote(root)
    found = {"root": root, "name": repo.split("/")[-1] if repo else root.name, "repo": repo, "branch": branch, "private": _visibility(repo) if repo else None,
             "sources": [], "catalogues": [], "markdown": [], "description": ""}
    # Python packages: src/<pkg>/__init__.py, <pkg>/__init__.py, and nested project folders
    seen = set()
    for init in sorted(root.glob("src/*/__init__.py")) + sorted(root.glob("*/__init__.py")) + sorted(root.glob("*/*/__init__.py")) \
            + sorted(root.glob("*/*/*/__init__.py")):
        pkg = init.parent
        rel = pkg.relative_to(root)
        if set(rel.parts) & (S.SKIP_DIRS | {"tests", "test", "examples", "templates", "fixtures"}) or any(p.startswith((".", "_")) for p in rel.parts):
            continue
        if str(rel) in seen or any(str(rel).startswith(s + "/") for s in seen):
            continue
        seen.add(str(rel))
        found["sources"].append({"path": str(rel), "language": "python", "name": pkg.name})
    # loose modules: a folder of .py files with no __init__.py (scripts, a flat tool)
    NOT_API = ("test_*.py", "*_test.py", "conftest.py", "setup.py", "dev_check*.py", "noxfile.py")
    skip_names = S.SKIP_DIRS | {"tests", "test", "examples", "templates", "fixtures", "docs-site", "scripts", "vendor", "validation"}
    dirs = [root] + sorted(d for pat in ("*", "*/*", "*/*/*") for d in root.glob(pat) if d.is_dir())
    for d in dirs:
        rel = d.relative_to(root)
        if any(p.startswith((".", "_")) or p in skip_names for p in rel.parts):
            continue
        if (d / "__init__.py").exists() or any(str(rel) == s or str(rel).startswith(s + "/") for s in seen):
            continue
        mods = [f for f in sorted(d.glob("*.py")) if not any(f.match(p) for p in NOT_API)]
        if len(mods) >= 2:
            found["sources"].append({"path": str(rel) if d != root else ".", "language": "python", "name": "",
                                     "title": found["name"] if d == root else d.name, "recursive": False, "exclude": list(NOT_API)})
    for lang, marker in (("typescript", "package.json"), ("swift", "Package.swift")):
        if (root / marker).exists() or (lang == "swift" and list(root.glob("*.xcodeproj"))):
            for cand in ("src", "Sources", "lib"):
                if (root / cand).is_dir() and S.files(root / cand, S.LANG_EXT[lang]):
                    found["sources"].append({"path": cand, "language": lang, "name": root.name})
                    break
            else:
                if lang == "swift":
                    for d in sorted(root.iterdir()):
                        if d.is_dir() and not d.name.startswith(".") and d.name not in S.SKIP_DIRS \
                                and not d.name.endswith(("Tests", ".xcodeproj")) and S.files(d, (".swift",)):
                            found["sources"].append({"path": d.name, "language": "swift", "name": d.name})
    # catalogues: a JSON file holding a list of objects that each have a name
    for f in sorted(root.rglob("catalog*.json")):
        if set(f.relative_to(root).parts) & S.SKIP_DIRS:
            continue
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        for key, val in (data.items() if isinstance(data, dict) else []):
            if isinstance(val, list) and val and all(isinstance(x, dict) and "name" in x for x in val):
                found["catalogues"].append({"file": str(f.relative_to(root)), "list": key, "n": len(val), "keys": sorted(val[0])})
    for f in sorted(root.rglob("*.md")):
        rel = f.relative_to(root)
        if set(rel.parts) & (S.SKIP_DIRS | {"LICENSES"}) or any(p.startswith(".") for p in rel.parts):
            continue
        found["markdown"].append(str(rel))
    readme = root / "README.md"
    if readme.exists():
        for line in readme.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "!", "[", "<", ">", "|", "-", "*", "`")):
                found["description"] = re.sub(r"[*_`]", "", line)[:220]
                break
    return found


def slug(s: dict) -> str:
    base = s.get("name") or (s["path"] if s["path"] != "." else s.get("title", "api"))
    return re.sub(r"[^a-z0-9]+", "-", f"{base}-{s['language']}".lower()).strip("-") if s["language"] != "python" else \
        re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-") or "api"


def propose(found: dict) -> str:
    """The docs-site.toml text for what detect() found, commented so it can be edited by hand."""
    q = json.dumps
    root: Path = found["root"]
    private = found["private"]
    lines = [
        f"# docs-site.toml for {found['name']}. Generated by `docsite init`; edit freely.",
        "# Reference: https://github.com/polarizetech/automatic-documentation-site/blob/main/docs/CONFIG.md",
        "",
        "[site]",
        f"name = {q(found['name'])}",
        f"title = {q(found['name'])}",
        f"tagline = {q(found['description'])}",
        f"repo = {q(found['repo'])}",
        f"branch = {q(found['branch'])}",
        f"private = {'true' if private is not False else 'false'}"
        + ("" if private is not None else "    # could not ask GitHub; assumed private, which is the safe default"),
        f"polarize_ui = {q(DEFAULT_POLARIZE_UI)}",
        "",
        "[guides]",
        "# Markdown that becomes pages. README.md is the overview.",
    ]
    md = found["markdown"]
    tops = sorted({m.split("/")[0] for m in md if "/" in m})
    include = ["README.md"] + [f"{t}/**/*.md" for t in tops]
    root_md = [m for m in md if "/" not in m and m not in ("README.md",)]
    include += [m for m in root_md if m.upper() not in ("CLAUDE.MD", "AGENTS.MD", "LICENSE.MD")]
    lines += [f"include = {q(include)}", 'exclude = ["**/CLAUDE.md", "**/AGENTS.md", "**/node_modules/**"]', ""]
    for s in found["sources"]:
        lines += ["[[source]]", f"path = {q(s['path'])}", f"language = {q(s['language'])}", f"name = {q(s['name'])}",
                  f"title = {q(s.get('title') or s['name'])}", f"slug = {q(slug(s))}", 'group = "Reference"']
        if s.get("recursive") is False:
            lines += ["recursive = false    # only the modules directly in this folder", f"exclude = {q(s['exclude'])}"]
        lines.append("")
    for c in found["catalogues"][:1]:
        keys = c["keys"]
        lines += ["[catalogue]", f"file = {q(c['file'])}", f"list = {q(c['list'])}", 'group = "Packages"',
                  f"# {c['n']} entries; an entry's keys: {', '.join(keys)}", "[catalogue.fields]"]
        for want, default in CATALOGUE_FIELDS.items():
            guess = default if dig({k: {} for k in keys}, default.split(".")[0]) is not None else None
            if guess:
                lines.append(f"{want} = {q(default)}")
        lines.append("")
    lines += ["# [stories]", '# dir = "docs-site/stories"      # real calls, run at build time; see docs/STORIES.md',
              '# python = ".venv/bin/python"     # the interpreter that can import this repository', ""]
    return "\n".join(lines)
