"""Build a repository's docs site from its docs-site.toml.

Nothing on the site is typed in by hand. Each page is assembled from what the repository
already says about itself, and names its source so a wrong page is fixed at the source:

    Markdown ([guides])      README and docs become pages; a text-only repository stops here
    source ([[source]])      public functions, classes and types, read without importing
    catalogue ([catalogue])  a JSON list of extensions/providers/plugins: one page per entry
    stories ([stories])      real calls run at build time, in the repository's own interpreter
    datasets ([datasets.*])  licence and citation for every dataset a story touches
    plugin                   pages only this repository has (docs-site/pages.py)

The page layer (layout, components, search, plots, fonts) is polarize-ui's docs layer, fetched
at a pinned release; this package writes markup for it and holds no CSS or JS of its own.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, mdlite, polarize_ui
from .config import CATALOGUE_FIELDS, Config, dig, load
from .html import STORIES, callout, chip, chips, codewin, empty, esc, h2, page_head, pkgcard, slugify
from .readers import source as S

ICONS = {
    "menu": '<svg viewBox="0 0 20 20"><path d="M3 6h14M3 10h14M3 14h14" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    "search": '<svg viewBox="0 0 20 20" width="15" height="15"><circle cx="9" cy="9" r="5.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="m13.2 13.2 3.8 3.8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    "sun": '<svg class="ui-docsite__sun" viewBox="0 0 20 20"><circle cx="10" cy="10" r="3.4" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M10 1.8v2M10 16.2v2M1.8 10h2M16.2 10h2M4.2 4.2l1.4 1.4M14.4 14.4l1.4 1.4M4.2 15.8l1.4-1.4M14.4 5.6l1.4-1.4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "moon": '<svg class="ui-docsite__moon" viewBox="0 0 20 20"><path d="M16 12.5A6.5 6.5 0 0 1 7.5 4a6.5 6.5 0 1 0 8.5 8.5Z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>',
    "github": '<svg viewBox="0 0 16 16"><path fill="currentColor" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/></svg>',
    "arrow": '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M4 10h11M11 5l5 5-5 5"/></svg>',
}
#: Set by `docsite dev`: a script that reloads the page when the site is rebuilt. Empty in a build.
DEV_RELOAD = ""

GLYPHS = [
    '<path d="M2 12c2-6 4-6 6 0s4 6 6 0 4-6 6 0" />', '<path d="M3 18V8M8 18V4M13 18v-7M18 18V9" />',
    '<circle cx="11" cy="11" r="7"/><path d="M11 4v14M4 11h14"/>', '<path d="M3 11h4l2-6 4 12 2-6h4"/>',
    '<path d="M4 17 11 4l7 13z"/><path d="M7.5 12h7"/>', '<path d="M6 6c3 3 7 3 10 0M6 16c3-3 7-3 10 0M11 3v16"/>',
]


def glyph(i: int) -> str:
    return (f'<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
            f'stroke-linejoin="round">{GLYPHS[i % len(GLYPHS)]}</svg>')


class Site:
    """Everything the build knows, and the pages it will write."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.pages: list[dict] = []        # {slug, title, nav, group, parent, eyebrow, body, toc, wide}
        self.search: list[dict] = []
        self.api_index: dict[str, str] = {}
        self.stories: list[dict] = []
        self.captures: dict[str, str] = {}
        self.problems: list[dict] = []
        self.layer = ""
        self.sha = _git(cfg.root, "rev-parse", "--short", "HEAD") or "uncommitted"

    def add(self, slug, title, body, *, group, nav=None, parent=None, eyebrow="", toc=(), wide=False, meta=""):
        self.pages.append({"slug": slug, "title": title, "nav": nav or title, "group": group, "parent": parent,
                           "eyebrow": eyebrow, "body": body, "toc": list(toc), "wide": wide, "meta": meta})

    def stories_for(self, slug: str) -> list[dict]:
        return [s for s in self.stories if s["page"] == slug]


def _git(root: Path, *args) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return ""


# ── stories & plugin: run in the repository's interpreter ────────────────────────────────────

def run_repo_code(site: Site, refresh: bool) -> list[dict]:
    cfg = site.cfg
    st = cfg.stories
    sdir, plugin = st.get("dir", ""), st.get("plugin", "")
    hero = cfg.hero if cfg.hero.get("run") and cfg.hero.get("code") else {}
    plugin_pages: list[dict] = []
    if (sdir and (cfg.root / sdir).is_dir()) or (plugin and (cfg.root / plugin).exists()) or hero:
        # the interpreter that can import this repository: DOCSITE_PYTHON, then [stories] python
        # if it exists here, then the one running the build (what CI uses after its setup step)
        py = os.environ.get("DOCSITE_PYTHON") or st.get("python", "")
        if py and not os.path.isabs(py):
            py = str(cfg.root / py)
        if not py or not Path(py).exists():
            py = sys.executable
        cache = cfg.root / "docs-site" / ".cache"
        cache.mkdir(parents=True, exist_ok=True)
        out = cache / "runner.json"
        out.unlink(missing_ok=True)
        cmd = [py, "-m", "autodocsite.runner", "--root", str(cfg.root), "--cache", str(cache), "--out", str(out),
               "--salt", site.sha + _dirty(cfg.root), "--stories", sdir, "--plugin", plugin]
        for p in st.get("path", []):
            cmd += ["--path", p]
        if hero:
            cmd += ["--capture", f"hero={hero['code']}"]
        if refresh:
            cmd.append("--refresh")
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(
            [str(Path(__file__).resolve().parent.parent)] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else []))}
        r = subprocess.run(cmd, cwd=cfg.root, env=env)
        if r.returncode != 0 or not out.exists():
            site.problems.append({"file": "stories", "error": f"the story runner exited {r.returncode} under {py}", "trace": ""})
        else:
            data = json.loads(out.read_text())
            site.stories += data["stories"]
            site.captures.update(data["captures"])
            site.problems += data["problems"]
            plugin_pages = data["pages"]
    # stories in any language: a command that prints a view as JSON
    for s in cfg.story:
        rec = {"id": s["id"], "title": s.get("title", s["id"]), "summary": s.get("summary", ""), "page": s.get("page", "index"),
               "dataset": s.get("dataset"), "calls": s.get("calls", []), "badge": s.get("badge", "MEASURED"),
               "file": s.get("file", ""), "lang": s.get("language", ""), "built": time.strftime("%Y-%m-%d %H:%M")}
        rec["code"] = (cfg.root / s["file"]).read_text().strip() if s.get("file") and (cfg.root / s["file"]).exists() else s.get("command", "")
        t = time.time()
        try:
            r = subprocess.run(s["command"], shell=True, cwd=cfg.root, capture_output=True, text=True, timeout=s.get("timeout", 600))
            if r.returncode != 0:
                raise RuntimeError(f"exit {r.returncode}: {r.stderr.strip()[-600:]}")
            rec.update(ok=True, view=json.loads(r.stdout), seconds=round(time.time() - t, 2))
            print(f"  ✓ {s['id']:28s} {rec['seconds']:.1f}s", file=sys.stderr)
        except Exception as ex:
            rec.update(ok=False, error=f"{type(ex).__name__}: {ex}", trace="")
            print(f"  ✗ {s['id']:28s} {rec['error']}", file=sys.stderr)
        site.stories.append(rec)
    return plugin_pages


def _dirty(root: Path) -> str:
    return "+dirty" if _git(root, "status", "--porcelain", "--untracked-files=no") else ""


# ── rendering ────────────────────────────────────────────────────────────────────────────────

def dataset_chip(cfg: Config, key: str) -> str:
    d = cfg.datasets.get(key)
    if not d:
        return f'<span class="ui-chip">{esc(key)}</span>'
    return (f'<a class="ui-chip" href="datasets.html#{esc(key)}" title="{esc(d.get("cite", ""))}"><span class="ui-chip__dot"></span>'
            f'{esc(d.get("short", key))} <span class="ui-chip__lic">{esc(d.get("license", "no licence stated"))}</span></a>')


def render_story(site: Site, s: dict) -> str:
    cfg = site.cfg
    sid = f"story-{s['id']}"
    calls = "".join(f'<a class="ui-chip" href="{esc(site.api_index.get(c, "#"))}"><code>{esc(c)}</code></a>' for c in s.get("calls", []))
    head = f"""
    <div class="ui-example__head">
      <div><h3 id="{sid}" class="ui-example__title">{esc(s['title'])}</h3>
        <p class="ui-example__summary">{mdlite.inline(s.get('summary', ''))}</p></div>
      <div class="ui-example__meta">{dataset_chip(cfg, s['dataset']) if s.get('dataset') else ''}{calls}</div>
    </div>"""
    notice = ""
    if s.get("unavailable"):
        last = s.get("last_good")
        notice = callout("Service unavailable when this page was built",
                         f"<p><code>{esc(s.get('error', ''))}</code></p><p>This is an outage of the service, not a failure of the code shown. "
                         + (f"Below is the last successful run, from {esc(last.get('built', 'an earlier build'))}." if last else
                            "There is no earlier successful run to show.") + "</p>", "info")
        if not last:
            return f'<section class="ui-example" data-story="{esc(s["id"])}">{head}{codewin(s.get("code", ""), name=s.get("file") or s["id"])}<div style="height:14px"></div>{notice}</section>'
        s = {**s, **{k: last[k] for k in ("view", "seconds", "built") if k in last}, "ok": True}
    if not s.get("ok"):
        return f"""<section class="ui-example">{head}
        <div class="ui-example__error"><span class="ui-example__failed">Story failed</span> <code>{esc(s.get('error', 'not run'))}</code>
        {f'<details><summary>Traceback</summary><pre>{esc(s["trace"])}</pre></details>' if s.get('trace') else ''}</div></section>"""
    v = s["view"]
    facts = "".join(f'<div class="ui-facts__item"><dt>{esc(k)}</dt><dd>{esc(str(val))}</dd></div>' for k, val in v.get("facts", []))
    tabs = [(k, v.get(k) or []) for k in ("output", "input") if v.get(k)]
    payload = esc(json.dumps({k: specs for k, specs in tabs}, separators=(",", ":")))
    tab_html = "".join(f'<button class="ui-example__tab" role="tab" aria-selected="{"true" if i == 0 else "false"}" data-ui-tab="{k}">{k.title()}</button>'
                       for i, (k, _) in enumerate(tabs))
    raw = ""
    if v.get("raw") is not None:
        raw = (f'<details class="ui-example__raw"><summary>Raw result (JSON)</summary><pre><code>'
               f'{esc(json.dumps(v["raw"], indent=2, default=str)[:20000])}</code></pre></details>')
    lang = s.get("lang") or ("python" if s.get("file", "").endswith(".py") or not s.get("file") else Path(s["file"]).suffix.lstrip("."))
    badge = f'<ui-tier tier="{esc(s["badge"])}"></ui-tier>' if s.get("badge") else ""
    return f"""<section class="ui-example" data-story="{esc(s['id'])}">{head}{notice}
      <div class="ui-example__grid">
        {codewin(s.get('code', ''), name=s.get('file') or s['id'], lang=lang)}
        <div class="ui-example__io" data-ui-tabs>
          <div class="ui-example__tabs" role="tablist">{tab_html}<span class="ui-example__spacer"></span>{badge}</div>
          <div class="ui-example__body" data-ui-plots="{payload}"></div>
        </div>
      </div>
      {f'<dl class="ui-facts">{facts}</dl>' if facts else ''}
      {raw}
      <p class="ui-example__foot">Ran {esc(s.get('built', ''))} at {esc(site.sha)} in {s.get('seconds', '?')} s. Output is computed at build time; plots decimate long traces for display only.</p>
    </section>"""


def stories_block(site: Site, slug: str, toc: list, *, lead="Real calls, run when this page was built. The code is the story file itself.",
                  when_empty: str | None = None) -> str:
    stories = site.stories_for(slug)
    if not stories and when_empty is None:
        return ""
    toc.append((2, "stories", "Stories"))
    toc += [(3, f"story-{s['id']}", s["title"]) for s in stories]
    return h2("stories", "Stories", lead) + ("".join(render_story(site, s) for s in stories) or empty(when_empty or ""))


def source_link(cfg: Config, path: str, line: int | None = None) -> str:
    return f"{cfg.repo_url}/blob/{cfg.branch}/{path}" + (f"#L{line}" if line else "") if cfg.repo_url else ""


def render_api(site: Site, modules: list[dict]) -> tuple[str, list]:
    blocks, toc = [], []
    for m in modules:
        if not m["api"]:
            continue
        mid = f"mod-{slugify(m['qual'])}"
        toc.append((3, mid, m["qual"]))
        items = []
        for a in m["api"]:
            doc_rest = a["doc"][len(a["summary"]):].strip() if a["doc"].strip().startswith(a["summary"][:20]) and a["summary"] else a["doc"]
            src = source_link(site.cfg, m["path"], a["line"])
            items.append(f"""
            <article class="ui-apientry" id="api-{slugify(a['qual'])}">
              <div class="ui-apientry__head"><span class="ui-apientry__kind">{esc(a['kind'])}</span><h4 class="ui-apientry__name"><code>{esc(a['name'])}</code></h4>
                {f'<a class="ui-apientry__src" href="{esc(src)}">source</a>' if src else ''}</div>
              <pre class="ui-apientry__sig"><code>{esc(a['sig'])}</code></pre>
              {f'<div class="ui-apientry__doc ui-docsite__prose">{mdlite.render(a["summary"])}</div>' if a['summary'] else ''}
              {f'<details class="ui-apientry__more"><summary>Full documentation</summary><div class="ui-docsite__prose">{mdlite.render(doc_rest)}</div></details>' if doc_rest.strip() else ''}
            </article>""")
        blocks.append(f"""<section class="ui-apimod"><h3 id="{mid}" class="ui-apimod__title"><code>{esc(m['qual'])}</code></h3>
          <p class="ui-apimod__sum">{mdlite.inline(m['summary'])}</p>{''.join(items)}</section>""")
    return "".join(blocks), toc


def modlist(modules: list[dict], link: bool) -> str:
    rows = "".join(
        (f'<a class="ui-modlist__row" href="#mod-{slugify(m["qual"])}">' if link and m["api"] else '<div class="ui-modlist__row">')
        + f'<code>{esc(m["qual"])}</code><span>{mdlite.inline(m["summary"][:220])}</span>' + ("</a>" if link and m["api"] else "</div>")
        for m in modules)
    return f'<div class="ui-modlist">{rows}</div>'


def index_api(site: Site, slug: str, modules: list[dict], alias_prefix: str = ""):
    for m in modules:
        site.api_index[m["qual"]] = f"{slug}.html#mod-{slugify(m['qual'])}"
        site.search.append({"t": m["qual"], "s": m["summary"][:140], "h": site.api_index[m["qual"]], "k": "Module"})
        for a in m["api"]:
            href = f"{slug}.html#api-{slugify(a['qual'])}"
            site.api_index[a["qual"]] = href
            if alias_prefix:
                site.api_index.setdefault(f"{alias_prefix}.{a['name']}", href)
            site.search.append({"t": a["qual"], "s": a["summary"][:140], "h": href, "k": a["kind"]})


# ── page builders ────────────────────────────────────────────────────────────────────────────

def guide_files(cfg: Config) -> list[tuple[Path, dict]]:
    """(file, settings) for every Markdown page: named [[guide]] entries first, then the globs."""
    out, seen = [], set()
    for g in cfg.guide:
        f = cfg.root / g["file"]
        if f.is_file():
            out.append((f, g)); seen.add(f.resolve())
    include = cfg.guides.get("include", ["README.md", "docs/**/*.md"])
    exclude = cfg.guides.get("exclude", []) + ["**/node_modules/**", "docs-site/**"]
    for pat in include:
        for f in sorted(cfg.root.glob(pat)):
            rel = str(f.relative_to(cfg.root))
            if f.is_file() and f.resolve() not in seen and not any(fnmatch.fnmatch(rel, e) for e in exclude) \
                    and not (set(Path(rel).parts) & S.SKIP_DIRS):
                out.append((f, {})); seen.add(f.resolve())
    return out


def guide_slug(rel: Path) -> str:
    return "readme" if str(rel).lower() == "readme.md" else slugify(str(rel.with_suffix("")))


def build_guides(site: Site):
    cfg = site.cfg
    files = guide_files(cfg)
    slugs = {f.resolve(): g.get("slug") or guide_slug(f.relative_to(cfg.root)) for f, g in files}
    img_dir = site.dist / "assets" / "img"
    for f, g in files:
        rel = f.relative_to(cfg.root)
        text = f.read_text(errors="replace")

        def link(href, _f=f):
            target, _, frag = href.partition("#")
            p = (_f.parent / target).resolve() if target else _f.resolve()
            if p in slugs:
                return f"{slugs[p]}.html" + (f"#{frag}" if frag else "")
            try:
                relp = p.relative_to(cfg.root)
            except ValueError:
                return href
            return (f"{cfg.repo_url}/blob/{cfg.branch}/{relp}" if cfg.repo_url else href) + (f"#{frag}" if frag else "")

        def image(src, _f=f):
            p = (_f.parent / src.split("?")[0]).resolve()
            if not p.is_file() or cfg.root not in p.parents:
                return ""
            img_dir.mkdir(parents=True, exist_ok=True)
            name = hashlib.sha1(str(p).encode()).hexdigest()[:8] + "-" + p.name
            shutil.copy(p, img_dir / name)
            return f"assets/img/{name}"

        mdlite.LINKER, mdlite.IMAGER = link, image
        body, toc = mdlite.render(text, toc=True, drop_h1=True)
        mdlite.LINKER = mdlite.IMAGER = None
        h1 = re.search(r"^#\s+(.+)$", text, re.M)
        title = g.get("title") or (re.sub(r"[*_`]", "", h1.group(1)).strip() if h1 else rel.stem.replace("-", " ").replace("_", " "))
        group = g.get("group") or ("Introduction" if len(rel.parts) == 1 else rel.parts[0].replace("-", " ").replace("_", " ").title()
                                   if len(rel.parts) == 2 else " / ".join(p.replace("-", " ").title() for p in rel.parts[:2]))
        slug = slugs[f.resolve()]
        src = source_link(cfg, str(rel))
        lead = g.get("lead", "")
        toc = [t for t in toc if t[0] <= 3][:60]
        html = page_head(title, mdlite.inline(lead) if lead else "") + f'<div class="ui-docsite__prose">{body}</div>'
        html += stories_block(site, slug, toc)          # a story may sit on any page, a guide included
        html += f'<p class="ui-docsite__sublead" style="margin-top:28px">Rendered from <a href="{esc(src)}"><code>{esc(str(rel))}</code></a>.</p>' if src \
            else f'<p class="ui-docsite__sublead" style="margin-top:28px">Rendered from <code>{esc(str(rel))}</code>.</p>'
        site.add(slug, title, html, group=group, eyebrow=group, toc=toc,
                 nav=g.get("nav") or (title if len(title) <= 34 else rel.stem.replace("-", " ").replace("_", " ")))
        site.search.append({"t": title, "s": f"{group} · {rel}", "h": f"{slug}.html", "k": "Guide"})
        for lvl, hid, label in toc:
            if lvl == 2:
                site.search.append({"t": label, "s": title, "h": f"{slug}.html#{hid}", "k": "Section"})


def build_sources(site: Site) -> list[dict]:
    """Reads every [[source]]; pages are written later, once stories and the API index exist."""
    cfg, out = site.cfg, []
    for s in cfg.source:
        data = S.read(cfg.root, cfg.root / s["path"], s.get("language", "auto"), s.get("name", ""), s.get("exclude", []),
                      s.get("recursive", True))
        slug = s.get("slug") or slugify(s.get("name") or s["path"])
        index_api(site, slug, data["modules"])
        out.append({"cfg": s, "slug": slug, "data": data})
    return out


def write_source_pages(site: Site, sources: list[dict]):
    for src in sources:
        s, slug, data = src["cfg"], src["slug"], src["data"]
        title = s.get("title") or s.get("name") or s["path"]
        toc = []
        n_api = sum(len(m["api"]) for m in data["modules"])
        body = page_head(title, mdlite.inline(s.get("lead", "")) if s.get("lead") else "")
        body += chips(chip("language", f"<code>{esc(data['language'])}</code>"), chip("path", f"<code>{esc(s['path'])}</code>"),
                      chip("modules", str(len(data["modules"]))), chip("public symbols", str(n_api)))
        if data["doc"]:
            toc.append((2, "overview", "Overview"))
            body += h2("overview", "Overview") + f'<div class="ui-docsite__prose">{mdlite.render(data["doc"])}</div>'
        body += stories_block(site, slug, toc)
        if data["modules"]:
            toc.append((2, "modules", "Modules"))
            body += h2("modules", "Modules") + modlist(data["modules"], link=True)
        api_html, api_toc = render_api(site, data["modules"])
        if api_html:
            toc.append((2, "api", "API reference"))
            toc += api_toc
            body += h2("api", "API reference", "Read from the source without importing or running it.") + api_html
        if not data["modules"]:
            body += empty(f"No {esc(data['language'])} source was found under <code>{esc(s['path'])}</code>.")
        site.add(slug, title, body, group=s.get("group", "Reference"), eyebrow=s.get("group", "Reference"), toc=toc,
                 meta=s.get("meta", ""))
        site.search.append({"t": title, "s": f"{data['language']} · {s['path']}", "h": f"{slug}.html", "k": "Reference"})


def read_catalogue(site: Site) -> list[dict]:
    cfg = site.cfg
    c = cfg.catalogue
    if not c:
        return []
    raw = json.loads((cfg.root / c["file"]).read_text())
    entries = raw.get(c.get("list", "extensions"), []) if isinstance(raw, dict) else raw
    fields = {**CATALOGUE_FIELDS, **c.get("fields", {})}
    out = []
    for e in entries:
        f = {k: dig(e, path) for k, path in fields.items()}
        name = f["name"] or "unnamed"
        short = name.removeprefix(c.get("strip_prefix", ""))
        entry = {"raw": e, "name": name, "short": short, "slug": c.get("slug_prefix", "") + slugify(short), "version": f["version"] or "",
                 "summary": f["summary"] or "", "repo": f["repo"] or cfg.repo, "path": f["path"] or "", "import": f["import"] or "",
                 "requires": f["requires"] or "", "boundary": f["boundary"] or "", "uses": f["uses"] or [], "modules": [], "doc": "",
                 "in_repo": (f["repo"] or cfg.repo) == cfg.repo}
        fmt = {**{k: v for k, v in e.items() if isinstance(v, str)}, "repo": entry["repo"], "path": entry["path"],
               "import": entry["import"], "name": name, "short": short}
        if entry["in_repo"] and c.get("source"):
            try:
                src_dir = cfg.root / c["source"].format(**fmt)
            except KeyError:
                src_dir = None
            if src_dir and src_dir.exists():
                data = S.read(cfg.root, src_dir, c.get("language", "auto"), entry["import"] or short)
                entry["modules"], entry["doc"] = data["modules"], data["doc"]
                prefix = c.get("uses_prefix")
                if prefix:
                    entry["uses"] = sorted(i for i in data["imports"] if i.startswith(prefix + ".") and i.count(".") >= 2
                                           and not i.startswith(f"{prefix}.extensions"))
                index_api(site, entry["slug"], entry["modules"], alias_prefix=entry["import"])
        entry["install"] = c["install"].format(**fmt) if c.get("install") else ""
        out.append(entry)
    return out


def write_catalogue_pages(site: Site, entries: list[dict]):
    cfg = site.cfg
    c = cfg.catalogue
    group = c.get("group", "Packages")
    for e in entries:
        toc = [(2, "overview", "Overview")]
        summary = e["summary"] if len(e["summary"]) < 260 else e["summary"].split(";")[0] + "."
        body = page_head(e["short"], esc(summary))
        meta = [chip("version", f"<code>{esc(e['version'])}</code>")] if e["version"] else []
        if e["requires"]:
            meta.append(chip("requires", f"<code>{esc(e['requires'])}</code>"))
        if e["import"]:
            meta.append(chip("import", f"<code>{esc(e['import'])}</code>"))
        if e["path"]:
            meta.append(chip("lives in", f"<code>{esc(e['repo'].split('/')[-1])}/{esc(e['path'])}</code>"))
        body += chips(*meta)
        if e["install"]:
            body += codewin(e["install"], name="Install", lang="bash") + '<div style="height:22px"></div>'
        if e["boundary"]:
            body += callout("Claim boundary", f"<p>{esc(e['boundary'])}</p>", "warn")
        overview = mdlite.render(e["doc"]) if e["doc"] else f"<p>{esc(e['summary'])}</p>"
        if not e["in_repo"]:
            overview += callout("Lives in another repository",
                                f"<p>This entry is catalogued here but its code is in <code>{esc(e['repo'])}</code>"
                                + (f" at <code>{esc(e['path'])}</code>" if e["path"] else "")
                                + ". This page shows only what the catalogue records; its API and stories are generated in that repository.</p>"
                                + ("<p><strong>A change to anything under <em>Uses</em> below has a consumer this repository cannot test.</strong></p>" if e["uses"] else ""))
        body += h2("overview", "Overview") + f'<div class="ui-docsite__prose">{overview}</div>'
        children = [p for p in site.pages if p.get("parent") == e["slug"]]
        if children:
            toc.append((2, "sub-pages", c.get("children_title", "Sub-pages")))
            body += h2("sub-pages", c.get("children_title", "Sub-pages")) + '<div class="ui-pkgcards">' + "".join(
                pkgcard(f"{p['slug']}.html", p["nav"], p.get("card", ""), meta=p.get("meta", ""), icon_html=glyph(i),
                        foot_start=f"{len(site.stories_for(p['slug']))} stories") for i, p in enumerate(children)) + "</div>"
        own = site.stories_for(e["slug"])
        child_stories = sum(len(site.stories_for(p["slug"])) for p in children)
        body += stories_block(site, e["slug"], toc, when_empty=(
            "Every story here belongs to one of the sub-pages above." if child_stories and not own else
            "No stories yet." + ("" if e["in_repo"] else " They are generated in the owning repository.")))
        if e["uses"]:
            toc.append((2, "uses", "Uses"))
            body += h2("uses", "Uses", "Read from this package's own imports." if e["modules"] else "Declared in the catalogue.") + chips(*[
                f'<a class="ui-chip" href="{esc(site.api_index.get(u) or site.api_index.get(u.rsplit(".", 1)[0], "#"))}"><code>{esc(u)}</code></a>'
                for u in e["uses"]])
        api_html, api_toc = render_api(site, e["modules"])
        if api_html:
            toc.append((2, "api", "API reference"))
            toc += api_toc
            body += h2("api", "API reference") + api_html
        if e["modules"]:
            toc.append((2, "modules", "Modules"))
            body += h2("modules", "Modules") + modlist(e["modules"], link=False)
        site.add(e["slug"], e["short"], body, group=group, eyebrow=group.rstrip("s") if group.endswith("s") else group, toc=toc,
                 meta=e["version"] + ("" if e["in_repo"] else " ↗"))
        site.search.append({"t": e["short"], "s": e["summary"][:140], "h": f"{e['slug']}.html", "k": group.rstrip("s")})


def write_plugin_pages(site: Site, plugin_pages: list[dict]):
    for p in plugin_pages:
        toc = [tuple(t) for t in p.get("toc", [])]
        html = p.get("html", "")
        if STORIES in html:
            sub: list = []
            block = stories_block(site, p["slug"], sub, when_empty=p.get("stories_empty", "No stories yet."))
            html = html.replace(STORIES, block)
            at = next((i for i, t in enumerate(toc) if t[1] == "stories"), None)
            toc = toc + sub if at is None else toc[:at] + sub + toc[at + 1:]
        body = page_head(p["title"], esc(p.get("lead", ""))) + html
        site.pages.append({"slug": p["slug"], "title": p["title"], "nav": p.get("nav", p["title"]), "group": p.get("group", "Reference"),
                           "parent": p.get("parent"), "eyebrow": p.get("eyebrow", ""), "body": body, "toc": toc, "wide": False,
                           "meta": p.get("meta", ""), "card": p.get("card", "")})
        for s in p.get("search", []):
            site.search.append({"t": s["t"], "s": s.get("s", ""), "h": s.get("h") or f"{p['slug']}.html", "k": s.get("k", "Page")})


def build_datasets(site: Site):
    cfg = site.cfg
    if not cfg.datasets:
        return
    rows = []
    for key, d in cfg.datasets.items():
        used = [s for s in site.stories if s.get("dataset") == key]
        used_html = " ".join(f'<a class="ui-chip" href="{esc(s["page"])}.html#story-{esc(s["id"])}">{esc(s["title"])}</a>' for s in used) or "—"
        lic = d.get("license", "")
        dl = [("provider", (f'<a href="{esc(d["url"])}">{esc(d.get("provider", ""))}</a>' if d.get("url") else esc(d.get("provider", "")))
               + (f' · v{esc(str(d["version"]))}' if d.get("version") else ""))]
        if d.get("modality"):
            dl.append(("modality", esc(d["modality"])))
        if d.get("doi"):
            dl.append(("DOI", f'<a href="https://doi.org/{esc(d["doi"])}">{esc(d["doi"])}</a>'))
        dl.append(("licence", (f'<a href="{esc(d["license_url"])}">{esc(lic)}</a>' if d.get("license_url") else esc(lic)) or "<strong>none stated</strong>"))
        rows.append(f"""<section class="ui-dataset" id="{esc(key)}">
          <div class="ui-dataset__head"><h2>{esc(d.get('title', key))}</h2><span class="ui-dataset__lic">{esc(lic or 'no licence stated')}</span></div>
          {f'<p class="ui-dataset__why">{esc(d["why"])}</p>' if d.get('why') else ''}
          <dl class="ui-dataset__dl">{''.join(f'<div><dt>{k}</dt><dd>{v}</dd></div>' for k, v in dl)}</dl>
          {f'<p class="ui-dataset__cite"><span class="ui-chip__label">Cite</span> {esc(d["cite"])}</p>' if d.get('cite') else ''}
          <div class="ui-dataset__used ui-chips"><span class="ui-chip__label">Used by</span> {used_html}</div>
        </section>""")
        site.search.append({"t": d.get("title", key), "s": f"Dataset · {d.get('provider', '')} · {lic}", "h": f"datasets.html#{key}", "k": "Dataset"})
    body = page_head("Datasets", "Every story runs on data registered here, with its licence and citation. "
                     "Stories load data only through this registry, so an attribution cannot drift from the data it describes.") + "".join(rows)
    site.add("datasets", "Datasets", body, group="Introduction", eyebrow="Introduction",
             toc=[(2, k, d.get("short", k)) for k, d in cfg.datasets.items()])


def build_home(site: Site, sources: list[dict], entries: list[dict]):
    cfg = site.cfg
    name = cfg.name
    first_ref = next((p for p in site.pages if p["group"] != "Introduction"), None)
    first_guide = next((p for p in site.pages if p["slug"] == "readme"), None) or next(iter(site.pages), None)
    ctas = ""
    if first_guide:
        ctas += f'<a class="ui-cta ui-cta--solid" href="{first_guide["slug"]}.html"><span class="ui-cta__text">Read the overview</span></a>'
    if first_ref and first_ref is not first_guide:
        ctas += (f'<a class="ui-cta" href="{first_ref["slug"]}.html"><span class="ui-cta__icon">{ICONS["arrow"]}</span>'
                 f'<span class="ui-cta__text">{esc(first_ref["group"])}</span></a>')
    hero_code = ""
    h = cfg.hero
    if h.get("code") and (cfg.root / h["code"]).exists():
        code = (cfg.root / h["code"]).read_text().strip()
        hero_code = codewin(code, name=h.get("name", Path(h["code"]).suffix.lstrip(".") or "code"), lang=h.get("language", "python"),
                            copy=False, out=site.captures.get("hero", ""), note_html=esc(h.get("note", "")))
    n_api = sum(len(m["api"]) for s in sources for m in s["data"]["modules"]) + sum(len(m["api"]) for e in entries for m in e["modules"])
    n_mod = sum(len(s["data"]["modules"]) for s in sources) + sum(len(e["modules"]) for e in entries)
    ok = sum(1 for s in site.stories if s.get("ok"))
    guides = [p for p in site.pages if p["eyebrow"] == p["group"] and p["group"] not in ("Reference",) and p["slug"] not in ("datasets",)
              and not p.get("parent")]
    stats = [(len(entries), cfg.catalogue.get("group", "packages").lower()) if entries else None,
             (n_mod, "modules") if n_mod else None, (n_api, "public symbols") if n_api else None,
             (f"{ok}/{len(site.stories)}", "stories passing") if site.stories else None,
             (len(site.pages), "pages")]
    stats = [s for s in stats if s][:4]
    body = f"""
    <section class="ui-docsite__hero ui-cellfield-host" id="hero"{'' if hero_code else ' style="grid-template-columns:1fr"'}>
      <ui-cellfield hero="#hero" density="0.6" intensity="0.8"></ui-cellfield>
      <div>
        <p class="ui-docsite__kicker">{esc(cfg.site.get('kicker', name))}</p>
        <h1 class="ui-docsite__hero-title">{esc(cfg.site.get('title', name))}</h1>
        <p class="ui-docsite__hero-lead">{mdlite.inline(cfg.site.get('tagline', ''))}</p>
        <div class="ui-docsite__hero-actions">{ctas}</div>
      </div>
      {hero_code}
    </section>
    <div class="ui-statrow" style="grid-template-columns:repeat({len(stats)},1fr)">{''.join(f'<div class="ui-statrow__item"><span class="ui-statrow__n">{n}</span><span class="ui-statrow__label">{esc(l)}</span></div>' for n, l in stats)}</div>"""
    toc = []
    if entries:
        g = cfg.catalogue.get("group", "Packages")
        toc.append((2, "packages", g))
        body += h2("packages", g, mdlite.inline(cfg.catalogue.get("lead", ""))) + '<div class="ui-pkgcards">' + "".join(
            pkgcard(f"{e['slug']}.html", e["short"], e["summary"] if len(e["summary"]) < 200 else e["summary"].split(";")[0] + ".",
                    meta=e["version"], icon_html=glyph(i),
                    foot_start=_count(len(site.stories_for(e["slug"])) + sum(len(site.stories_for(p["slug"])) for p in site.pages if p.get("parent") == e["slug"]), "story", "stories"),
                    foot_end="in repo" if e["in_repo"] else "↗ " + e["repo"].split("/")[-1]) for i, e in enumerate(entries)) + "</div>"
    refs = [p for p in site.pages if p["group"] == "Reference" or any(p["slug"] == s["slug"] for s in sources)]
    if refs:
        toc.append((2, "reference", "Reference"))
        body += h2("reference", "Reference") + '<div class="ui-pkgcards">' + "".join(
            pkgcard(f"{p['slug']}.html", p["nav"], next((s["cfg"].get("lead", "") for s in sources if s["slug"] == p["slug"]), "")[:200],
                    icon_html=glyph(i + 2), foot_start=_count(len(site.stories_for(p["slug"])), "story", "stories")) for i, p in enumerate(refs)) + "</div>"
    if guides and not (entries or refs):
        toc.append((2, "guides", "Pages"))
        body += h2("guides", "Pages") + '<div class="ui-modlist">' + "".join(
            f'<a class="ui-modlist__row" href="{p["slug"]}.html"><code>{esc(p["nav"])}</code><span>{esc(p["group"])}</span></a>' for p in guides) + "</div>"
    made = [("Markdown", "READMEs and docs are rendered as pages. Edit the file, not the site.")]
    if sources or any(e["modules"] for e in entries):
        made.append(("Source", "Public functions, classes and types are read from the code without running it."))
    if entries:
        made.append(("Catalogue", f"<code>{esc(cfg.catalogue['file'])}</code> lists every entry. A new entry is a new page."))
    if site.stories:
        made.append(("Stories", "Each story is one real call, run at build time. Its source is the example shown."))
    if cfg.datasets:
        made.append(("Data", "Each dataset carries its licence and citation; a story's attribution comes from the same record."))
    toc.append((2, "how", "How this site is made"))
    body += h2("how", "How this site is made") + '<div class="ui-howto">' + "".join(
        f'<div class="ui-howto__item"><p class="ui-howto__step">{i} · {esc(s)}</p><p class="ui-howto__text">{t}</p></div>'
        for i, (s, t) in enumerate(made, 1)) + "</div>"
    if site.problems:
        body += h2("problems", "Build problems") + "".join(
            f'<div class="ui-example__error" style="margin-bottom:10px"><span class="ui-example__failed">{esc(p["file"])}</span> <code>{esc(p["error"])}</code>'
            + (f'<details><summary>Traceback</summary><pre>{esc(p["trace"])}</pre></details>' if p.get("trace") else "") + "</div>" for p in site.problems)
    site.pages.insert(0, {"slug": "index", "title": "Overview", "nav": "Overview", "group": "Introduction", "parent": None,
                          "eyebrow": "", "body": body, "toc": toc, "wide": True, "meta": ""})
    site.search.insert(0, {"t": "Overview", "s": f"{name} docs home", "h": "index.html", "k": "Guide"})


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


# ── the page shell ───────────────────────────────────────────────────────────────────────────

def nav_html(site: Site, current: str) -> str:
    groups: dict[str, list] = {}
    order = ["Introduction"]
    for p in site.pages:
        if p.get("parent"):
            continue
        groups.setdefault(p["group"], []).append(p)
        if p["group"] not in order:
            order.append(p["group"])

    def item(p, sub=False):
        cls = ' class="is-current" aria-current="page"' if p["slug"] == current else ""
        meta = f'<span class="ui-docsite__navmeta">{esc(p["meta"])}</span>' if p.get("meta") and not sub else ""
        out = f'<li{" class=is-sub" if sub else ""}><a href="{p["slug"]}.html"{cls}>{esc(p["nav"])}{meta}</a></li>'
        return out + "".join(item(c, True) for c in site.pages if c.get("parent") == p["slug"])

    return "".join(f'<div class="ui-docsite__navgroup"><h2 class="ui-docsite__navtitle">{esc(g)}</h2><ul>{"".join(item(p) for p in groups[g])}</ul></div>'
                   for g in order if g in groups)


def link_api_refs(site: Site, html: str) -> str:
    def one(m):
        name = m.group(1)
        href = site.api_index.get(name) or site.api_index.get(name.rsplit(".", 1)[0])
        return f'<a href="{esc(href)}"><code>{name}</code></a>' if href else f"<code>{name}</code>"
    return re.sub(r'<code class="api">([^<]+)</code>', one, html)


def page_html(site: Site, p: dict) -> str:
    cfg = site.cfg
    toc = p["toc"]
    toc_html = "".join(f'<li{" class=is-sub" if lvl >= 3 else ""}><a href="#{esc(i)}">{esc(t)}</a></li>' for lvl, i, t in toc)
    shell = "ui-docsite__shell" + (" ui-docsite__shell--wide" if p["wide"] or not toc else "")
    key = f"docs-theme-{slugify(cfg.name)}"
    robots = '<meta name="robots" content="noindex, nofollow">' if cfg.private else ""
    flag = '<span class="ui-docsite__flag" title="Private repository: not for publication">Private</span>' if cfg.private else ""
    gh = f'<a class="ui-docsite__iconbtn" href="{esc(cfg.repo_url)}" aria-label="Repository on GitHub">{ICONS["github"]}</a>' if cfg.repo_url else ""
    return f"""<!doctype html>
<html lang="en" data-ui-theme-key="{key}">
<head>
<meta charset="utf-8">
<script>/* under a path prefix the bare prefix needs its slash, or every relative link breaks */if(!/\\/$|\\.[a-z0-9]+$/i.test(location.pathname))location.replace(location.pathname+"/"+location.search+location.hash)</script>
<meta name="viewport" content="width=device-width, initial-scale=1">
{robots}
<title>{esc(p['title'])} · {esc(cfg.name)} docs</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect x='10' y='5' width='12' height='22' rx='2' fill='%230d6d6b'/%3E%3C/svg%3E">
<link rel="stylesheet" href="assets/design.css">
<link rel="stylesheet" href="assets/publication.css">
<link rel="stylesheet" href="assets/landing.css">
<link rel="stylesheet" href="assets/docs.css">
<script>try{{var t=localStorage.getItem('{key}');if(t)document.documentElement.dataset.theme=t}}catch(e){{}}</script>
<script defer src="assets/site-data.js"></script>
<script defer src="assets/design.classic.js"></script>
<script defer src="assets/docs.classic.js"></script>
<script defer src="assets/cellfield.classic.js"></script>{DEV_RELOAD}
</head>
<body class="ui ui-docsite">
<header class="ui-docsite__bar">
  <button class="ui-docsite__iconbtn ui-docsite__navtoggle" aria-label="Open navigation" data-ui-nav-toggle>{ICONS['menu']}</button>
  <a class="ui-docsite__brand ui-brand" href="index.html" aria-label="{esc(cfg.name)} docs, home">
    <span class="ui-brand__mark" aria-hidden="true"></span>
    <span class="ui-brand__word">{esc(cfg.name)}</span><span class="ui-docsite__brand-sub">docs</span>
  </a>
  <button class="ui-docsite__search-btn" data-ui-search-open>{ICONS['search']}<span>Search docs</span><kbd>⌘K</kbd></button>
  <div class="ui-docsite__actions">{flag}
    <button class="ui-docsite__iconbtn" data-ui-theme-toggle aria-label="Toggle colour theme">{ICONS['sun']}{ICONS['moon']}</button>{gh}
  </div>
</header>
<div class="{shell}">
  <nav class="ui-docsite__nav" aria-label="Documentation">{nav_html(site, p['slug'])}</nav>
  <main class="ui-docsite__main" id="main">
    {f'<p class="ui-docsite__eyebrow">{esc(p["eyebrow"])}</p>' if p['eyebrow'] else ''}
    {link_api_refs(site, p['body'])}
    <footer class="ui-docsite__foot">Generated from {f'<code>{esc(cfg.repo)}</code>' if cfg.repo else 'this repository'} at <code>{esc(site.sha)}</code> by automatic-documentation-site {esc(__version__)}, on {esc(site.layer)}. Nothing on this page is written by hand; edit the source it names.</footer>
  </main>
  {f'<aside class="ui-docsite__toc" aria-label="On this page"><h2 class="ui-docsite__navtitle">On this page</h2><ul>{toc_html}</ul></aside>' if toc and not p['wide'] else ''}
</div>
<div class="ui-docsearch" data-ui-search="assets/search.json" hidden>
  <div class="ui-docsearch__panel" role="dialog" aria-label="Search">
    <input class="ui-docsearch__input" type="search" placeholder="Search pages, functions, stories…" autocomplete="off">
    <ul class="ui-docsearch__results"></ul>
    <p class="ui-docsearch__hint"><kbd>↑</kbd><kbd>↓</kbd> to move · <kbd>↵</kbd> to open · <kbd>esc</kbd> to close</p>
  </div>
</div>
</body>
</html>"""


# ── orchestration ────────────────────────────────────────────────────────────────────────────

def build(root: Path, out: Path | None = None, refresh: bool = False) -> dict:
    t0 = time.time()
    cfg = load(root)
    site = Site(cfg)
    site.dist = (out or cfg.root / "docs-site" / "dist").resolve()
    if site.dist.exists():
        shutil.rmtree(site.dist)
    (site.dist / "assets").mkdir(parents=True)
    site.layer, site_data = polarize_ui.install(site.dist / "assets", cfg.site.get("polarize_ui"))

    sources = build_sources(site)
    entries = read_catalogue(site)
    plugin_pages = run_repo_code(site, refresh)
    build_guides(site)
    write_source_pages(site, sources)
    write_plugin_pages(site, plugin_pages)   # before catalogue pages: an entry lists its sub-pages
    write_catalogue_pages(site, entries)
    for s in site.stories:
        site.search.append({"t": s["title"], "s": f"Story · {s['page']}" + (f" · {cfg.datasets.get(s['dataset'], {}).get('short', s['dataset'])}" if s.get("dataset") else ""),
                            "h": f"{s['page']}.html#story-{s['id']}", "k": "Story"})
    build_datasets(site)
    orphan = sorted({s["page"] for s in site.stories} - {p["slug"] for p in site.pages} - {"index"})
    if orphan:   # a story that names no page would vanish; say so on the home page instead
        site.problems.append({"file": "stories", "error": f"stories name page(s) that do not exist: {orphan}", "trace": ""})
    build_home(site, sources, entries)

    # catalogue entries follow their group order; sub-pages render under their parent in the nav
    slugs = set()
    for p in site.pages:
        if p["slug"] in slugs:
            raise SystemExit(f"two pages share the slug {p['slug']!r}; set a `slug` on one of them in docs-site.toml")
        slugs.add(p["slug"])
        (site.dist / f"{p['slug']}.html").write_text(page_html(site, p))
    (site.dist / "assets" / "search.json").write_text(json.dumps(site.search))
    # Everything the scripts would fetch, as one classic script: a page opened from a folder
    # (file://) cannot fetch, and with this it does not need to.
    site_data["search.json"] = site.search
    (site.dist / "assets" / "site-data.js").write_text(
        "window.__docsiteData = " + json.dumps(site_data, separators=(",", ":")).replace("</", "<\\/") + ";\n")
    report = {"pages": len(site.pages), "stories": len(site.stories), "stories_ok": sum(1 for s in site.stories if s.get("ok")),
              "stories_unavailable": sum(1 for s in site.stories if s.get("unavailable")),
              "problems": site.problems, "dist": str(site.dist), "seconds": round(time.time() - t0, 1), "layer": site.layer,
              "sha": site.sha, "private": cfg.private, "name": cfg.name, "repo": cfg.repo}
    (site.dist / "docs-site.json").write_text(json.dumps({k: v for k, v in report.items() if k != "dist"}, indent=1))
    return report
