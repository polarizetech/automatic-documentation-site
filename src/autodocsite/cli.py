"""docsite: generate a repository's docs site, install its workflow, and host the results.

    docsite init <repo>            look at a repository; write docs-site.toml and the workflow
    docsite build [repo]           build the site into <repo>/docs-site/dist
    docsite sync                   (host) pull every configured repository's built site
    docsite serve                  (host) serve them on localhost for a tailnet-only mount
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import CONFIG_NAME, detect, propose

WORKFLOW = """\
# Rebuilds this repository's docs site on every push to {branch}.
# Installed by `docsite init`. The steps live in automatic-documentation-site, so a fix there
# reaches this repository by bumping the tag below. Guide:
# https://github.com/polarizetech/automatic-documentation-site/blob/main/docs/WORKFLOW.md
name: docs-site
on:
  push:
    branches: [{branch}]
  workflow_dispatch:
permissions:
{permissions}
concurrency:
  group: docs-site
  cancel-in-progress: true
jobs:
  docs:
    uses: polarizetech/automatic-documentation-site/.github/workflows/docs-site.yml@v{version}
    with:
      publish: {publish}   # {publish_note}
      # setup: pip install -e .     # what stories need in order to import this repository
"""
GITIGNORE = ["docs-site/dist/", "docs-site/.cache/"]


def cmd_init(a) -> int:
    root = Path(a.repo).resolve()
    if not root.is_dir():
        raise SystemExit(f"{root} is not a directory")
    found = detect(root)
    private = found["private"] is not False
    print(f"repository   {found['repo'] or '(no GitHub remote)'}  [{'private' if found['private'] else 'public' if found['private'] is False else 'visibility unknown: treated as private'}]")
    print(f"markdown     {len(found['markdown'])} files")
    for s in found["sources"]:
        print(f"source       {s['path']}  ({s['language']})")
    for c in found["catalogues"]:
        print(f"catalogue    {c['file']}  [{c['list']}: {c['n']} entries]")
    if not (found["sources"] or found["catalogues"]):
        print("             no source or catalogue found: the site will be this repository's Markdown")
    cfg_path = root / CONFIG_NAME
    text = propose(found)
    publish = a.publish or ("branch" if private else "pages")
    if publish == "pages" and private:
        raise SystemExit("refusing: a private repository's site is never published to GitHub Pages. Use --publish branch.")
    wf = WORKFLOW.format(
        branch=found["branch"], version=__version__, publish=publish,
        permissions="  contents: write" if publish == "branch" else "  contents: read\n  pages: write\n  id-token: write",
        publish_note="commits the built site to the docs-site branch; the tailnet host pulls it" if publish == "branch"
        else "deploys to GitHub Pages (enable Pages with source 'GitHub Actions' in the repository settings)")
    wf_path = root / ".github" / "workflows" / "docs-site.yml"
    if not a.write:
        print(f"\n--- {cfg_path.name} (proposed; pass --write to create it) ---\n{text}")
        print(f"--- {wf_path.relative_to(root)} (proposed) ---\n{wf}")
        return 0
    for path, body in ((cfg_path, text), (wf_path, wf)):
        if path.exists() and not a.force:
            print(f"kept         {path.relative_to(root)} (exists; --force overwrites)")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        print(f"wrote        {path.relative_to(root)}")
    gi = root / ".gitignore"
    have = gi.read_text().splitlines() if gi.exists() else []
    add = [g for g in GITIGNORE if g not in have]
    if add:
        gi.write_text("\n".join(have + ["", "# automatic-documentation-site: build output and story cache"] + add) + "\n")
        print(f"updated      .gitignore (+{', '.join(add)})")
    print(f"\nnext: docsite build {a.repo}")
    return 0


def cmd_build(a) -> int:
    from .build import build
    root = Path(a.repo).resolve()
    if a.publish == "pages":
        from .config import load
        if load(root).private:
            raise SystemExit("refusing: docs-site.toml says `private = true`, and a private site is never published to GitHub Pages.")
    r = build(root, Path(a.out).resolve() if a.out else None, refresh=a.refresh)
    stories = f"{r['stories_ok']}/{r['stories']} stories passing, " if r["stories"] else ""
    print(f"{r['name']}: {r['pages']} pages, {stories}{r['seconds']}s, {r['layer']} → {r['dist']}")
    for p in r["problems"]:
        print(f"  problem  {p['file']}: {p['error']}", file=sys.stderr)
    failed = r["stories"] - r["stories_ok"]
    if a.strict and (failed or r["problems"]):
        print(f"--strict: {failed} failed stories, {len(r['problems'])} problems", file=sys.stderr)
        return 1
    return 0


def cmd_sync(a) -> int:
    from . import host
    for r in host.sync(host.load(Path(a.hosts) if a.hosts else None)):
        print(f"{r['path']:<34} {r['status']:<12} {r['detail']}")
    return 0


def cmd_serve(a) -> int:
    from . import host
    host.serve(host.load(Path(a.hosts) if a.hosts else None), a.port, a.sync_every)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="docsite", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="inspect a repository; propose (or --write) docs-site.toml and the workflow")
    p.add_argument("repo")
    p.add_argument("--write", action="store_true", help="create the files instead of printing them")
    p.add_argument("--force", action="store_true", help="overwrite files that exist")
    p.add_argument("--publish", choices=["branch", "pages", "artifact"], help="default: pages if public, branch if private")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("build", help="build the site")
    p.add_argument("repo", nargs="?", default=".")
    p.add_argument("--out", help="output directory (default <repo>/docs-site/dist)")
    p.add_argument("--refresh", action="store_true", help="re-run every story, ignoring the cache")
    p.add_argument("--strict", action="store_true", help="exit 1 if any story failed or any problem was recorded")
    p.add_argument("--publish", choices=["branch", "pages", "artifact"], help="where the result is going; pages is refused for a private site")
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("sync", help="(host) pull every configured repository's built site")
    p.add_argument("--hosts")
    p.set_defaults(fn=cmd_sync)
    p = sub.add_parser("serve", help="(host) serve the synced sites on localhost")
    p.add_argument("--hosts")
    p.add_argument("--port", type=int)
    p.add_argument("--sync-every", type=int, default=0, metavar="SECONDS", help="also sync on this interval")
    p.set_defaults(fn=cmd_serve)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
