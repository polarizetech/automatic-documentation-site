"""`docsite dev`: build, serve on localhost, open the browser, rebuild and reload on change.

The one command for reading a repository's docs while working on it, the way `storybook dev`
is for components. Nothing is published and nothing but this machine can reach it (127.0.0.1).

    docsite dev path/to/repo

A dev build goes to docs-site/.cache/dev, so docs-site/dist stays whatever `docsite build`
last wrote. Each page carries a small script that asks the server for the build number once a
second and reloads when it changes; that script exists only in dev builds.
"""
from __future__ import annotations

import http.server
import shutil
import socket
import sys
import threading
import time
import traceback
import webbrowser
from functools import partial
from pathlib import Path

from . import build as B
from .readers.source import SKIP_DIRS

WATCHED = {".md", ".toml", ".json", ".py", ".ts", ".tsx", ".js", ".mjs", ".jsx", ".swift", ".png", ".jpg", ".svg"}
RELOAD = """
<script>(() => { let seen = null; setInterval(async () => { try {
  const v = await (await fetch('__docsite/version', { cache: 'no-store' })).text();
  if (seen !== null && v !== seen) location.reload(); seen = v;
} catch (e) { /* the server is rebuilding or gone; keep the page */ } }, 1000); })();</script>"""


def snapshot(root: Path) -> dict[str, float]:
    out = {}
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if p.suffix not in WATCHED or set(rel.parts) & SKIP_DIRS or (rel.parts[:1] == ("docs-site",) and rel.parts[1:2] in (("dist",), (".cache",))):
            continue
        try:
            out[str(rel)] = p.stat().st_mtime
        except OSError:
            pass
    return out


def free_port(start: int) -> int:
    for port in range(start, start + 50):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit(f"no free port in {start}-{start + 49}")


def dev(root: Path, port: int = 8300, open_browser: bool = True, refresh: bool = False) -> None:
    root = root.resolve()
    out = root / "docs-site" / ".cache" / "dev"
    staging = root / "docs-site" / ".cache" / "dev.next"
    state = {"version": 0}

    def rebuild(first: bool = False) -> bool:
        B.DEV_RELOAD = RELOAD
        try:
            r = B.build(root, staging, refresh=refresh and first)
        except SystemExit as ex:          # a config error: say it, keep serving the last good build
            print(f"build failed: {ex}", file=sys.stderr)
            return False
        except Exception:
            traceback.print_exc()
            return False
        finally:
            B.DEV_RELOAD = ""
        shutil.rmtree(out, ignore_errors=True)
        staging.rename(out)
        state["version"] += 1
        stories = f", {r['stories_ok']}/{r['stories']} stories passing" if r["stories"] else ""
        stories += f", {r['stories_unavailable']} unavailable" if r.get("stories_unavailable") else ""
        print(f"built {r['pages']} pages{stories} in {r['seconds']}s" + (f"  ({len(r['problems'])} problems, shown on the home page)" if r["problems"] else ""), flush=True)
        return True

    if not rebuild(first=True):
        raise SystemExit(1)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?")[0].endswith("/__docsite/version"):
                body = str(state["version"]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def log_message(self, fmt, *args):
            pass

    port = free_port(port)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(out)))
    url = f"http://127.0.0.1:{port}/"
    print(f"docs for {root.name} at {url}   (watching for changes; Ctrl-C to stop)", flush=True)

    def watch():
        last = snapshot(root)
        while True:
            time.sleep(1)
            now = snapshot(root)
            if now != last:
                changed = sorted(set(now.items()) ^ set(last.items()))
                names = sorted({k for k, _ in changed})
                print(f"changed: {', '.join(names[:4])}{' …' if len(names) > 4 else ''}", flush=True)
                last = now
                rebuild()

    threading.Thread(target=watch, daemon=True).start()
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
