"""Where a site's page layer comes from: polarize-ui, pinned to a release tag.

Every site renders with polarize-ui's docs layer (docs.css + docs.js) on top of its tokens,
fonts and landing components. Like every polarize-ui consumer, a site pins a RELEASE TAG
(`[site] polarize_ui` in docs-site.toml) rather than following main, so a polarize-ui release
can never change a site without an edit in that site's repository.

    POLARIZE_UI_REF   overrides the tag for one build
    POLARIZE_UI       a local checkout to use instead, for developing the design and a site at once

A fetched tag is cached under ~/.cache/automatic-documentation-site/polarize-ui/<tag>/.
"""
from __future__ import annotations

import io
import os
import shutil
import tarfile
import urllib.request
from pathlib import Path

#: The release used when docs-site.toml names none: the first with the docs layer.
PINNED = "v0.5.15"

#: Everything the pages link. A tag missing any of these is too old for this site.
FILES = ("design.css", "design.js", "tokens.json", "publication.css", "landing.css",
         "docs.css", "docs.js", "cellfield.js")

CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "automatic-documentation-site" / "polarize-ui"


def source(ref: str | None = None) -> tuple[Path, str]:
    """(directory holding the files, a label saying where they came from)."""
    local = os.environ.get("POLARIZE_UI")
    if local:
        path = Path(local).expanduser().resolve()
        _require(path, f"POLARIZE_UI={path}")
        return path, f"polarize-ui (local checkout)"
    ref = os.environ.get("POLARIZE_UI_REF") or ref or PINNED
    path = CACHE / ref
    if not (path / "docs.css").exists():
        url = f"https://codeload.github.com/polarizetech/polarize-ui/tar.gz/refs/tags/{ref}"
        try:
            data = urllib.request.urlopen(url, timeout=60).read()
        except Exception as ex:  # a network or missing-tag failure says what to do
            raise SystemExit(f"could not fetch polarize-ui {ref} ({ex}). Set POLARIZE_UI to a local "
                             f"checkout, or POLARIZE_UI_REF to a released tag.") from ex
        tmp = CACHE / f".{ref}.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            try:
                tar.extractall(tmp, filter="data")
            except TypeError:
                tar.extractall(tmp)
        (inner,) = list(tmp.iterdir())
        shutil.rmtree(path, ignore_errors=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        inner.rename(path)
        shutil.rmtree(tmp, ignore_errors=True)
    _require(path, f"polarize-ui {ref}")
    return path, f"polarize-ui {ref}"


def _require(path: Path, label: str) -> None:
    missing = [f for f in FILES if not (path / f).exists()] + ([] if (path / "fonts").is_dir() else ["fonts/"])
    if missing:
        raise SystemExit(f"{label} has no {', '.join(missing)}: the docs layer needs polarize-ui with docs.css "
                         f"(first released in v0.5.15).")


#: The layer's scripts. polarize-ui ships them as ES modules; a site loads the classic copies.
SCRIPTS = ("design.js", "docs.js", "cellfield.js")

_PRELUDE = """\
/* {name}: polarize-ui's ES module, made a classic script by automatic-documentation-site so the
 * site opens from a folder (file://) as well as from a server. Mechanical: `export` removed,
 * import.meta.url replaced, wrapped for top-level await. Data it fetches (tokens, the search
 * index, the icon sprite) is read from site-data.js when the build embedded it. */
(async () => {{
const __src = (document.currentScript && document.currentScript.src) || location.href;
const fetch = (u, ...rest) => {{
  const key = String(u).split(/[?#]/)[0].split('/').pop();
  const d = (window.__docsiteData || {{}})[key];
  if (d === undefined) return window.fetch(u, ...rest);
  const text = typeof d === 'string' ? d : JSON.stringify(d);
  return Promise.resolve({{ ok: true, status: 200, json: async () => JSON.parse(text), text: async () => text }});
}};
"""


def classic(name: str, source: str) -> str:
    """An ES module as a classic script. Refuses, by name, anything it cannot convert faithfully."""
    import re
    if re.search(r"^\s*import\s+[^(]|^\s*export\s+(default\b|\{|\*)|\bimport\s*\(", source, re.M):
        raise SystemExit(f"polarize-ui's {name} now uses import/export forms the classic conversion does not handle "
                         f"(static or dynamic import, export default, export lists). Pin an earlier polarize-ui "
                         f"release in docs-site.toml, or update autodocsite.polarize_ui.classic().")
    body = re.sub(r"^(\s*)export\s+(?=(?:async\s+)?(?:function|const|let|var|class)\b)", r"\1", source, flags=re.M)
    body = body.replace("import.meta.url", "__src")
    return _PRELUDE.format(name=name) + body + "\n})().catch((e) => console.error('" + name + "', e));\n"


def embedded(src: Path) -> dict:
    """What the layer's scripts fetch at runtime, to embed in site-data.js (keyed by file name)."""
    import json
    out = {}
    if (src / "tokens.json").exists():
        out["tokens.json"] = json.loads((src / "tokens.json").read_text())
    sprite = src / "icons" / "polarize-icons.svg"
    if sprite.exists():
        out["polarize-icons.svg"] = sprite.read_text()
    return out


def install(dest: Path, ref: str | None = None) -> tuple[str, dict]:
    """Copy the page layer into dest/ (assets/ of the built site).

    Returns (the source label, the data to embed in site-data.js). Each script is also written
    as `<name>.classic.js`, which is what pages load.
    """
    src, label = source(ref)
    (dest / "fonts").mkdir(parents=True, exist_ok=True)
    for f in FILES:
        shutil.copy(src / f, dest / f)
    for f in (src / "fonts").iterdir():
        if f.is_file():
            shutil.copy(f, dest / "fonts" / f.name)
    for name in SCRIPTS:
        (dest / name.replace(".js", ".classic.js")).write_text(classic(name, (src / name).read_text()))
    return label, embedded(src)
