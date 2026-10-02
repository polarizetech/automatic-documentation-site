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
PINNED = "v0.5.13"

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
                         f"(first released after v0.5.12).")


def install(dest: Path, ref: str | None = None) -> str:
    """Copy the page layer into dest/ (assets/ of the built site). Returns the source label."""
    src, label = source(ref)
    (dest / "fonts").mkdir(parents=True, exist_ok=True)
    for f in FILES:
        shutil.copy(src / f, dest / f)
    for f in (src / "fonts").iterdir():
        if f.is_file():
            shutil.copy(f, dest / "fonts" / f.name)
    return label
