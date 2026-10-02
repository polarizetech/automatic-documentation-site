"""Optional host: pull several repositories' built sites and serve them from one machine.

A PRIVATE repository's site is never published to the web. Its workflow commits the built site
to a `docs-site` branch in the same private repository; the machine that serves the tailnet
pulls those branches (`docsite sync`) and serves them on localhost (`docsite serve`), which a
tailnet-only Tailscale mount exposes. Which repositories a host serves is LOCAL configuration,
never committed to this (public) repository:

    ~/.config/automatic-documentation-site/hosts.toml

    port = 8251
    [[site]]
    repo = "owner/private-repo"      # its docs-site branch is cloned with your git credentials
    path = "private-repo"            # served at /<path>/ (default: the repository name)
    [[site]]
    dir = "~/Sites/some-repo/docs-site/dist"   # or a local build, served as-is
    path = "some-repo"

Bound to 127.0.0.1. Never mount it on a Funnel listener.
"""
from __future__ import annotations

import html
import http.server
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import unquote

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "automatic-documentation-site" / "hosts.toml"
SITES = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "automatic-documentation-site" / "sites"


def load(path: Path | None = None) -> dict:
    path = path or CONFIG
    if not path.exists():
        raise SystemExit(f"{path} not found. Create it with one [[site]] per repository; see docs/HOSTING.md.")
    cfg = tomllib.loads(path.read_text())
    for s in cfg.get("site", []):
        s.setdefault("path", (s.get("repo", "") or s.get("dir", "")).rstrip("/").split("/")[-1])
        s.setdefault("branch", "docs-site")
        s["local"] = Path(s["dir"]).expanduser() if s.get("dir") else SITES / s["path"]
    return cfg


def sync(cfg: dict) -> list[dict]:
    """Bring every repo-backed site up to date. Returns one status per site; never raises on one failure."""
    out = []
    for s in cfg.get("site", []):
        if s.get("dir"):
            out.append({"path": s["path"], "status": "local" if s["local"].is_dir() else "missing", "detail": str(s["local"])})
            continue
        url, dest = f"https://github.com/{s['repo']}.git", s["local"]
        try:
            if (dest / ".git").is_dir():
                subprocess.run(["git", "-C", str(dest), "fetch", "--depth", "1", "origin", s["branch"]], check=True, capture_output=True, timeout=120)
                before = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
                subprocess.run(["git", "-C", str(dest), "reset", "--hard", "FETCH_HEAD"], check=True, capture_output=True)
                after = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
                out.append({"path": s["path"], "status": "updated" if before != after else "current", "detail": after[:9]})
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["git", "clone", "--depth", "1", "--single-branch", "--branch", s["branch"], url, str(dest)],
                               check=True, capture_output=True, timeout=300)
                out.append({"path": s["path"], "status": "cloned", "detail": s["repo"]})
        except subprocess.CalledProcessError as ex:
            msg = (ex.stderr or b"").decode(errors="replace").strip().splitlines()[-1:] or ["git failed"]
            out.append({"path": s["path"], "status": "unavailable", "detail": msg[0]})
        except Exception as ex:
            out.append({"path": s["path"], "status": "unavailable", "detail": f"{type(ex).__name__}: {ex}"})
    return out


def _meta(d: Path) -> dict:
    try:
        return json.loads((d / "docs-site.json").read_text())
    except Exception:
        return {}


def index_page(cfg: dict) -> bytes:
    rows = []
    for s in cfg.get("site", []):
        d = s["local"]
        m = _meta(d)
        if (d / "index.html").exists():
            rows.append(f'<li><a href="{html.escape(s["path"])}/">{html.escape(m.get("name", s["path"]))}</a> '
                        f'<small>{html.escape(m.get("repo", s.get("repo", "")))} · {html.escape(m.get("sha", ""))}'
                        f'{" · private" if m.get("private") else ""}</small></li>')
        else:
            rows.append(f'<li>{html.escape(s["path"])} <small>not built or not synced yet</small></li>')
    return (f"""<!doctype html><meta charset=utf-8><meta name=robots content="noindex, nofollow"><title>docs</title>
<script>if(!/\\/$/.test(location.pathname))location.replace(location.pathname+"/")</script>
<body style="font:15px/1.7 system-ui;max-width:42rem;margin:4rem auto;padding:0 1rem">
<h1 style="font-weight:400">Docs</h1><ul>{''.join(rows)}</ul>
<p><small>Served by automatic-documentation-site. Tailnet only.</small></p>""").encode()


def serve(cfg: dict, port: int | None = None, sync_every: int = 0) -> None:
    port = port or cfg.get("port", 8251)
    sites = {s["path"]: s["local"] for s in cfg.get("site", [])}

    class Handler(http.server.SimpleHTTPRequestHandler):
        def translate_path(self, path):
            parts = [p for p in unquote(path.split("?", 1)[0].split("#", 1)[0]).split("/") if p and p not in (".", "..")]
            if not parts or parts[0] not in sites or (len(parts) > 1 and parts[1] == ".git"):
                return str(SITES / "__none__")
            return str(sites[parts[0]].joinpath(*parts[1:]))

        def do_GET(self):
            if self.path.split("?")[0] in ("/", ""):
                body = index_page(cfg)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def list_directory(self, path):
            self.send_error(404, "Not found")
            return None

        def end_headers(self):
            self.send_header("X-Robots-Tag", "noindex, nofollow")
            self.send_header("Cache-Control", "no-cache")
            super().end_headers()

        def log_message(self, fmt, *args):
            sys.stderr.write("docsite %s\n" % (fmt % args))

    if sync_every:
        def loop():
            while True:
                for r in sync(cfg):
                    if r["status"] in ("updated", "cloned", "unavailable"):
                        sys.stderr.write(f"docsite sync {r['path']}: {r['status']} {r['detail']}\n")
                time.sleep(sync_every)
        threading.Thread(target=loop, daemon=True).start()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"docs on http://127.0.0.1:{port}/  ({', '.join('/' + p + '/' for p in sites) or 'no sites'})", flush=True)
    server.serve_forever()
