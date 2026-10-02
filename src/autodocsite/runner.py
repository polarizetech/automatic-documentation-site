"""Runs a repository's stories and page plugins INSIDE that repository's own interpreter.

The builder itself is stdlib-only and knows nothing about a repository's dependencies. Stories
import the repository's code (and numpy, scipy, whatever it needs), so they run in a
subprocess under the interpreter docs-site.toml names (`[stories] python`), with this package
on PYTHONPATH. The result is one JSON file the builder reads back:

    {"stories": [{id, title, summary, page, dataset, calls, badge, code, file,
                  ok, view | error+trace, seconds, built}],
     "pages":   [...what the plugin's pages(ctx) returned...],
     "captures": {name: stdout}}

Story results are cached under <cache>/stories/<id>.json, keyed on the story module's full
source and the salt the builder passes (versions). A failure is never cached and never
dropped: it is returned with its traceback and the page shows it as failed.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import sys
import time
import traceback
from pathlib import Path


def _default(o):
    if hasattr(o, "tolist"):
        return o.tolist()
    if hasattr(o, "item"):
        return o.item()
    if hasattr(o, "__dict__"):
        return vars(o)
    return str(o)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--stories", default="")
    ap.add_argument("--plugin", default="")
    ap.add_argument("--capture", action="append", default=[], help="name=path of a script whose stdout to capture")
    ap.add_argument("--path", action="append", default=[])
    ap.add_argument("--cache", required=True)
    ap.add_argument("--salt", default="")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    root = Path(a.root).resolve()
    cache = Path(a.cache) / "stories"
    cache.mkdir(parents=True, exist_ok=True)
    for p in reversed(a.path):
        sys.path.insert(0, str((root / p).resolve()))
    out = {"stories": [], "pages": [], "captures": {}, "problems": []}

    from autodocsite import story as S

    sdir = (root / a.stories) if a.stories else None
    if sdir and sdir.is_dir():
        # LAST on the path, not first: a story file is often named after the package it
        # demonstrates (stories/mylib.py), and `import mylib` inside it must find the package.
        # Helper modules beside the stories (datasets.py) are still importable.
        sys.path.append(str(sdir))
        for f in sorted(sdir.glob("*.py")):
            if f.name.startswith("_"):
                continue
            try:
                _load(f, f"docs_site_stories_{f.stem}")
            except Exception as ex:   # a story FILE that cannot import is reported, loudly
                out["problems"].append({"file": str(f.relative_to(root)), "error": f"{type(ex).__name__}: {ex}",
                                        "trace": traceback.format_exc()})
        seen: dict[str, str] = {}
        for s in S.REGISTRY:
            if s.id in seen:   # two stories with one id would share an anchor and a cache entry
                out["problems"].append({"file": s.file, "error": f"story id {s.id!r} is already used in {seen[s.id]}", "trace": ""})
                continue
            seen[s.id] = s.file
            src = Path(s.file).read_text() if s.file else s.code
            key = hashlib.sha256((src + s.id + a.salt).encode()).hexdigest()[:16]
            rec_path = cache / f"{s.id}.json"
            meta = {"id": s.id, "title": s.title, "summary": s.summary, "page": s.page, "dataset": s.dataset,
                    "calls": list(s.calls), "badge": s.badge, "code": s.code,
                    "file": str(Path(s.file).resolve().relative_to(root)) if s.file else ""}
            if not a.refresh and rec_path.exists():
                rec = json.loads(rec_path.read_text())
                if rec.get("key") == key and rec.get("ok"):
                    out["stories"].append({**rec, **meta, "cached": True})
                    print(f"  · {s.id:28s} cached", file=sys.stderr)
                    continue
            t = time.time()
            try:
                v = s.fn()
                rec = {"key": key, "ok": True, "view": json.loads(json.dumps(v, default=_default)),
                       "seconds": round(time.time() - t, 2), "built": time.strftime("%Y-%m-%d %H:%M")}
                rec_path.write_text(json.dumps(rec))
                print(f"  ✓ {s.id:28s} {rec['seconds']:.1f}s", file=sys.stderr)
            except Exception as ex:
                rec = {"key": key, "ok": False, "error": f"{type(ex).__name__}: {ex}", "trace": traceback.format_exc(),
                       "built": time.strftime("%Y-%m-%d %H:%M")}
                print(f"  ✗ {s.id:28s} {rec['error']}", file=sys.stderr)
            out["stories"].append({**rec, **meta})

    for item in a.capture:
        name, _, path = item.partition("=")
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                exec(compile((root / path).read_text(), path, "exec"), {"__name__": "__main__"})
            out["captures"][name] = buf.getvalue().rstrip()
        except Exception as ex:
            out["captures"][name] = f"[could not run: {type(ex).__name__}: {ex}]"

    if a.plugin and (root / a.plugin).exists():
        try:
            mod = _load(root / a.plugin, "docs_site_plugin")
            ctx = {"root": str(root), "stories": [{"id": s["id"], "page": s["page"], "title": s["title"]} for s in out["stories"]]}
            out["pages"] = json.loads(json.dumps(mod.pages(ctx), default=_default))
        except Exception as ex:
            out["problems"].append({"file": a.plugin, "error": f"{type(ex).__name__}: {ex}", "trace": traceback.format_exc()})

    Path(a.out).write_text(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
