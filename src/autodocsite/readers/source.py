"""Read a source tree's PUBLIC surface without importing or executing any of it.

One reader per language, one shape out:

    module = {name, qual, path, summary, doc, api: [entry]}
    entry  = {name, qual, kind, sig, summary, doc, line}

Python is read with `ast` (exact). TypeScript/JavaScript and Swift are read by their exported
or public declarations and the doc comment directly above each (`/** */`, `///`). That is a
declaration scan, not a compiler: it finds what a reader of the file would call the public
API, and it says nothing about types it cannot see on the declaration line.

A repository with no source at all needs none of this; its site is its Markdown.
"""
from __future__ import annotations

import ast
import fnmatch
import re
from pathlib import Path

SKIP_DIRS = {"node_modules", ".venv", "venv", ".git", "dist", "build", "__pycache__", ".claude",
             "site-packages", ".build", "DerivedData", "Pods", ".next", "coverage"}
LANG_EXT = {
    "python": (".py",),
    "typescript": (".ts", ".tsx", ".js", ".mjs", ".jsx"),
    "swift": (".swift",),
}


def first_para(doc: str) -> str:
    return (doc or "").strip().split("\n\n", 1)[0].replace("\n", " ").strip()


def files(root: Path, exts, exclude=(), recursive: bool = True) -> list[Path]:
    out = []
    for p in sorted(root.rglob("*") if recursive else root.glob("*")):
        rel = p.relative_to(root)
        # an exclude matches the file name (`test_*.py`) or its path under the source (`vendor/*`,
        # where * also crosses folders)
        if p.suffix in exts and p.is_file() and not (set(rel.parts) & SKIP_DIRS) \
                and not any(p.match(pat) or fnmatch.fnmatch(rel.as_posix(), pat) for pat in exclude):
            out.append(p)
    return out


def detect_language(root: Path) -> str | None:
    counts = {lang: len(files(root, exts)) for lang, exts in LANG_EXT.items()}
    lang = max(counts, key=counts.get)
    return lang if counts[lang] else None


# ── Python ───────────────────────────────────────────────────────────────────────────────────

def _py_entries(path: Path, qual: str) -> tuple[str, list[dict]]:
    tree = ast.parse(path.read_text())
    names = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "__all__" for t in node.targets):
            try:
                names = set(ast.literal_eval(node.value))
            except Exception:
                pass
    out = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) or node.name.startswith("_"):
            continue
        if names is not None and node.name not in names:
            continue
        doc = ast.get_docstring(node) or ""
        if isinstance(node, ast.ClassDef):
            fields = [f"{ast.unparse(s.target)}: {ast.unparse(s.annotation)}" for s in node.body if isinstance(s, ast.AnnAssign)]
            sig = f"class {node.name}" + (f"({', '.join(ast.unparse(b) for b in node.bases)})" if node.bases else "")
            if fields:
                sig += "\n    " + "\n    ".join(fields[:14]) + ("\n    …" if len(fields) > 14 else "")
            kind = "class"
        else:
            sig = f"{node.name}({ast.unparse(node.args)})" + (f" -> {ast.unparse(node.returns)}" if node.returns else "")
            kind = "function"
        out.append({"name": node.name, "qual": f"{qual}.{node.name}", "kind": kind, "sig": sig,
                    "summary": first_para(doc), "doc": doc, "line": node.lineno})
    return ast.get_docstring(tree) or "", out


def read_python(root: Path, src: Path, prefix: str, exclude=(), recursive: bool = True) -> dict:
    """`src` is a package directory (or a single file); `prefix` its import name."""
    mods, pkg_doc, imports = [], "", set()
    paths = [src] if src.is_file() else files(src, (".py",), exclude, recursive)
    for f in paths:
        try:
            tree_src = f.read_text()
            doc, api = _py_entries(f, "")
        except SyntaxError:
            continue
        rel = f.relative_to(src) if src.is_dir() else Path(f.name)
        parts = [p for p in rel.with_suffix("").parts if p != "__init__"]
        if src.is_file():          # one file IS the module: `name` is its import name
            qual = prefix or f.stem
        else:
            qual = ".".join([prefix] + parts) if prefix else ".".join(parts) or f.stem
        for node in ast.walk(ast.parse(tree_src)):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports |= {f"{node.module}.{a.name}" for a in node.names}
            elif isinstance(node, ast.Import):
                imports |= {a.name for a in node.names}
        if f.name == "__init__.py" and rel.parent == Path("."):
            pkg_doc = doc
            continue
        if f.name.startswith("_"):
            continue
        for e in api:
            e["qual"] = f"{qual}.{e['name']}"
        mods.append({"name": parts[-1] if parts else f.stem, "qual": qual, "path": str(f.relative_to(root)),
                     "summary": first_para(doc), "doc": doc, "api": api})
    return {"language": "python", "doc": pkg_doc, "modules": mods, "imports": sorted(imports)}


# ── TypeScript / JavaScript ──────────────────────────────────────────────────────────────────

_TS_DECL = re.compile(
    r"^export\s+(?:default\s+)?(?:declare\s+)?(?:async\s+)?(function\*?|const|let|class|interface|type|enum)\s+([A-Za-z_$][\w$]*)([^\n]*)",
    re.M)


def _block_comment_before(text: str, pos: int) -> str:
    head = text[:pos].rstrip()
    if not head.endswith("*/"):
        return ""
    start = head.rfind("/**")
    if start < 0 or "*/" in head[start:-2]:
        return ""
    body = head[start + 3:-2]
    return "\n".join(re.sub(r"^\s*\* ?", "", l) for l in body.splitlines()).strip()


def read_typescript(root: Path, src: Path, prefix: str, exclude=(), recursive: bool = True) -> dict:
    mods = []
    for f in files(src, LANG_EXT["typescript"], tuple(exclude) + ("*.d.ts", "*.test.*", "*.spec.*", "*.stories.*"), recursive):
        text = f.read_text(errors="replace")
        api = []
        for m in _TS_DECL.finditer(text):
            kind, name, rest = m.group(1).rstrip("*"), m.group(2), m.group(3)
            sig = re.sub(r"\s*[{=]\s*$", "", f"{kind} {name}{rest}".strip())
            sig = re.sub(r"\s*=>\s*\{?\s*$", "", sig)
            doc = _block_comment_before(text, m.start())
            api.append({"name": name, "qual": "", "kind": {"const": "const", "let": "const"}.get(kind, kind),
                        "sig": sig[:400], "summary": first_para(doc), "doc": doc, "line": text.count("\n", 0, m.start()) + 1})
        if not api:
            continue
        rel = f.relative_to(src).with_suffix("")
        qual = "/".join(([prefix] if prefix else []) + list(rel.parts))
        for e in api:
            e["qual"] = f"{qual}#{e['name']}"
        top = re.match(r"\s*/\*\*?(.*?)\*/", text, re.S)     # a file header: /** ... */ or /* ... */
        doc = "\n".join(re.sub(r"^\s*\* ?", "", l) for l in top.group(1).splitlines()).strip() if top else ""
        if not doc:
            lead = re.match(r"((?:\s*//[^\n]*\n)+)", text)
            doc = "\n".join(l.strip()[2:].strip() for l in lead.group(1).splitlines()) if lead else ""
        mods.append({"name": rel.name, "qual": qual, "path": str(f.relative_to(root)),
                     "summary": first_para(doc), "doc": doc, "api": api})
    js = sum(m["path"].endswith((".js", ".mjs", ".jsx")) for m in mods)
    return {"language": "javascript" if mods and js == len(mods) else "typescript", "doc": "", "modules": mods, "imports": []}


# ── Swift ────────────────────────────────────────────────────────────────────────────────────

_SWIFT_DECL = re.compile(
    r"^[ \t]*((?:@\w+(?:\([^)]*\))?\s+)*)(public|open)\s+((?:final\s+|static\s+|class\s+|mutating\s+|nonisolated\s+)*)"
    r"(func|struct|class|enum|protocol|actor|var|let|typealias|init)\b\s*([A-Za-z_]\w*)?([^\n{]*)", re.M)


def read_swift(root: Path, src: Path, prefix: str, exclude=(), recursive: bool = True) -> dict:
    mods = []
    for f in files(src, (".swift",), tuple(exclude) + ("*Tests.swift",), recursive):
        text = f.read_text(errors="replace")
        api = []
        for m in _SWIFT_DECL.finditer(text):
            kind, name, rest = m.group(4), m.group(5) or "init", m.group(6)
            lines = text[:m.start()].rstrip("\n").splitlines()
            doc = []
            while lines and lines[-1].strip().startswith("///"):
                doc.insert(0, lines.pop().strip()[3:].strip())
            sig = f"{m.group(2)} {m.group(3)}{kind} {m.group(5) or ''}{rest}".strip()
            api.append({"name": name, "qual": "", "kind": "function" if kind in ("func", "init") else kind,
                        "sig": re.sub(r"\s+", " ", sig)[:400], "summary": first_para("\n".join(doc)),
                        "doc": "\n".join(doc), "line": text.count("\n", 0, m.start()) + 1})
        if not api:
            continue
        rel = f.relative_to(src).with_suffix("")
        qual = ".".join(([prefix] if prefix else []) + list(rel.parts))
        for e in api:
            e["qual"] = f"{qual}.{e['name']}"
        lead = re.match(r"((?:\s*//[^\n]*\n)+)", text)
        doc = "\n".join(re.sub(r"^\s*//+ ?", "", l) for l in lead.group(1).splitlines()).strip() if lead else ""
        mods.append({"name": rel.name, "qual": qual, "path": str(f.relative_to(root)),
                     "summary": first_para(doc), "doc": doc, "api": api})
    return {"language": "swift", "doc": "", "modules": mods, "imports": []}


READERS = {"python": read_python, "typescript": read_typescript, "javascript": read_typescript, "swift": read_swift}


def read(root: Path, src: Path, language: str, prefix: str = "", exclude=(), recursive: bool = True) -> dict:
    if language == "auto":
        language = detect_language(src if src.is_dir() else src.parent) or "python"
    if language not in READERS:
        raise ValueError(f"no source reader for language {language!r} (have: {', '.join(sorted(READERS))})")
    return READERS[language](root, src, prefix, exclude, recursive)
