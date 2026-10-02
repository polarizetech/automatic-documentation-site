"""Stories: real calls, run at build time, shown with their code, input and output.

A story is ONE real call on ONE dataset. The page shows three things for it, all from the same
function so they cannot disagree:

    * the CODE: the story function's own source, as written (the usage example);
    * the INPUT: what went in, with the dataset's licence chip;
    * the OUTPUT: what came back, computed at build time, never typed in by hand.

A Python story:

    from autodocsite.story import story, view, trace, table

    @story(id="fit-line", title="Fit a line", page="core", dataset="synthetic",
           summary="...", calls=("mylib.fit",))
    def fit_line():
        import mylib
        result = mylib.fit(points)
        return view(input=[trace("points", y, fs)], output=[table("fit", ["k", "v"], rows)])

The body shown on the page is everything but the final `return view(...)`, with the story
module's own imports that the body uses prepended.

A story in ANY other language is a command that prints the same JSON `view` to stdout; see
`[[story]]` in docs-site.toml. This module is stdlib-only and does not need numpy: helpers
accept any sequence (numpy arrays included) and convert.
"""
from __future__ import annotations

import ast
import inspect
import math
import re
import textwrap
from dataclasses import dataclass
from typing import Callable

REGISTRY: list["Story"] = []


class Unavailable(Exception):
    """An outside service did not answer. NOT a failure of the story or the code it shows.

    A story that depends on a live service raises this (or wraps the call in `service(...)`)
    when the service is down, slow or rate-limiting. The page then says the service was
    unavailable when it was built and shows the story's last successful result, dated. It is
    never reported as a failed story, and `--strict` does not fail on it: a provider's outage
    is not the documented repository's regression. "Unavailable" never means "nothing exists".
    """


_NETWORK_MODULES = ("httpx", "httpcore", "requests", "urllib", "urllib3", "aiohttp", "botocore", "socket", "ssl", "http")


class service:
    """`with service("OpenNeuro"): ...` turns a network failure inside the block into Unavailable.

    Only transport failures are converted (timeouts, refused connections, DNS, TLS, HTTP-client
    errors). Anything else, including the documented code raising its own error, still fails
    the story as usual.
    """

    def __init__(self, name: str):
        self.name = name

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is None or isinstance(exc, Unavailable):
            return False
        chain, seen = [], set()
        e = exc
        while e is not None and id(e) not in seen:
            seen.add(id(e)); chain.append(e)
            e = e.__cause__ or e.__context__
        for e in chain:
            mod = type(e).__module__.split(".")[0]
            if isinstance(e, (TimeoutError, ConnectionError)) or mod in _NETWORK_MODULES:
                raise Unavailable(f"{self.name} did not answer: {type(e).__name__}: {e}") from exc
        return False


@dataclass
class Story:
    id: str
    title: str
    summary: str
    page: str                       # slug of the page it appears on
    fn: Callable
    dataset: str | None = None      # key in [datasets.*]
    calls: tuple[str, ...] = ()     # public names it exercises; linked to the API reference
    badge: str | None = "MEASURED"  # epistemic tier on the output; None for synthetic/modelled-without-claim
    code: str = ""
    file: str = ""


def story(*, id: str, title: str, summary: str, page: str, dataset: str | None = None,
          calls=(), badge: str | None = "MEASURED"):
    def wrap(fn):
        src = textwrap.dedent(inspect.getsource(fn))
        node = ast.parse(src).body[0]
        stmts = [s for s in node.body
                 if not (isinstance(s, ast.Expr) and isinstance(getattr(s, "value", None), ast.Constant))]
        if stmts and isinstance(stmts[-1], ast.Return):
            stmts = stmts[:-1]          # the trailing `return view(...)` is page layout, not usage
        lines = src.splitlines()
        code = textwrap.dedent("\n".join(lines[stmts[0].lineno - 1: stmts[-1].end_lineno])).strip() if stmts else ""
        mod = inspect.getmodule(fn)
        used = []
        for n in ast.parse(inspect.getsource(mod)).body if mod else []:
            if isinstance(n, (ast.Import, ast.ImportFrom)) and not (getattr(n, "module", "") or "").startswith("autodocsite"):
                names = [a.asname or a.name.split(".")[0] for a in n.names]
                if any(re.search(rf"\b{re.escape(x)}\b", code) for x in names):
                    used.append(ast.unparse(n))
        if used:
            code = "\n".join(used) + "\n\n" + code
        REGISTRY.append(Story(id, title, summary, page, fn, dataset, tuple(calls), badge, code,
                              getattr(mod, "__file__", "") or ""))
        return fn
    return wrap


# ── view helpers: the plot specs docs.js draws (polarize-ui docs.d.ts `PlotSpec`) ─────────────

def _seq(v) -> list[float]:
    if hasattr(v, "tolist"):
        v = v.tolist()
    return [float(x) for x in v]


def _num(x):
    return None if x is None or not math.isfinite(x) else float(f"{x:.5g}")


def decimate(x, y, n: int = 1600):
    """Min/max decimation for display: spikes stay visible at any zoom-out. Display only."""
    x, y = _seq(x), _seq(y)
    if len(y) <= n:
        return [_num(v) for v in x], [_num(v) for v in y]
    k = math.ceil(len(y) / (n // 2))
    xs, ys = [], []
    for i in range(0, len(y) - k + 1, k):
        chunk = y[i:i + k]
        lo = min(range(k), key=chunk.__getitem__)
        hi = max(range(k), key=chunk.__getitem__)
        for j in sorted((lo, hi)):
            xs.append(_num(x[i + j])); ys.append(_num(chunk[j]))
    return xs, ys


def trace(title, y=None, fs: float = 1.0, *, seconds=None, unit="", series=None, markers=(), caption=""):
    """A time-domain plot. `series` = {name: 1-D sequence} for several channels (stacked)."""
    series = series or {title: y}
    out = []
    for name, s in series.items():
        s = _seq(s)
        if seconds:
            s = s[: int(seconds * fs)]
        xs, ys = decimate([i / fs for i in range(len(s))], s)
        out.append({"name": name, "x": xs, "y": ys})
    return {"type": "line", "title": title, "series": out, "xlabel": "time (s)", "ylabel": unit,
            "xunit": "s", "yunit": unit, "markers": list(markers), "caption": caption, "stack": len(out) > 1}


def line(title, x, y=None, *, series=None, xlabel="", ylabel="", xunit="", yunit="", markers=(), caption=""):
    """A general x/y plot. `series` = {name: (x, y)} for several lines on shared axes."""
    series = series or {title: (x, y)}
    out = []
    for name, (sx, sy) in series.items():
        xs, ys = decimate(sx, sy, n=2400)
        out.append({"name": name, "x": xs, "y": ys})
    return {"type": "line", "title": title, "series": out, "xlabel": xlabel, "ylabel": ylabel,
            "xunit": xunit, "yunit": yunit, "markers": list(markers), "caption": caption}


def spectrum(title, f, p, *, fmax=None, fmin=0.0, markers=(), caption="", db=True, name="PSD"):
    f, p = _seq(f), _seq(p)
    keep = [i for i, v in enumerate(f) if v >= fmin and (fmax is None or v <= fmax)]
    y = [10 * math.log10(max(p[i], 1e-30)) if db else p[i] for i in keep]
    xs, ys = decimate([f[i] for i in keep], y, n=2400)
    return {"type": "line", "title": title, "series": [{"name": name, "x": xs, "y": ys}],
            "xlabel": "frequency (Hz)", "ylabel": "power (dB)" if db else "power", "xunit": "Hz",
            "yunit": "dB" if db else "", "markers": list(markers), "caption": caption}


def stems(title, groups, *, caption="", xmax=None):
    """Small multiples of line spectra: groups = [{name, lines:[{x, y}], invert?, flags?, note?}]."""
    return {"type": "stems", "title": title, "groups": groups, "caption": caption, "xmax": xmax}


def bars(title, items, *, caption="", unit=""):
    return {"type": "bars", "title": title, "items": [{"label": str(k), "value": float(v)} for k, v in items],
            "caption": caption}


def table(title, columns, rows, *, caption=""):
    def cell(v):
        if isinstance(v, bool):
            return str(v)
        if isinstance(v, float) or (hasattr(v, "item") and not isinstance(v, (str, bytes))):
            v = float(v)
            return f"{v:.4g}" if math.isfinite(v) else "—"
        return "—" if v is None else str(v)
    return {"type": "table", "title": title, "columns": [str(c) for c in columns],
            "rows": [[cell(c) for c in r] for r in rows], "caption": caption}


def verdicts(title, items, *, caption=""):
    """items = [{key, verdict, reason?, meta?, tone?}]: the verdict WORD is always shown."""
    return {"type": "verdicts", "title": title, "items": items, "caption": caption}


def view(*, input=(), output=(), facts=(), raw=None):
    """What a story returns. `facts` = [(label, value)]: the headline readout under the plots."""
    return {"input": list(input), "output": list(output), "facts": [[str(k), str(v)] for k, v in facts], "raw": raw}
