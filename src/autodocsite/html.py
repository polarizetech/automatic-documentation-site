"""Markup helpers for polarize-ui's docs layer (docs.css). Stdlib only.

Used by the builder, and importable by a repository's page plugin (docs-site/pages.py) so a
custom page is written in the same components as every generated one. Every helper escapes the
text it is given unless the parameter says it takes HTML.
"""
from __future__ import annotations

import html as _html
import re

esc = _html.escape


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def chip(label: str, value_html: str, href: str = "") -> str:
    inner = f'<span class="ui-chip__label">{esc(label)}</span>{value_html}'
    return f'<a class="ui-chip" href="{esc(href)}">{inner}</a>' if href else f'<span class="ui-chip">{inner}</span>'


def chips(*items: str) -> str:
    return f'<div class="ui-chips">{"".join(items)}</div>'


def h2(id_: str, title: str, lead_html: str = "") -> str:
    return (f'<h2 id="{esc(id_)}" class="ui-docsite__h2">{esc(title)}</h2>'
            + (f'<p class="ui-docsite__sublead">{lead_html}</p>' if lead_html else ""))


def page_head(title: str, lead_html: str = "") -> str:
    return f'<h1 class="ui-docsite__title">{esc(title)}</h1>' + (f'<p class="ui-docsite__lead">{lead_html}</p>' if lead_html else "")


def codewin(code: str, *, name: str = "", lang: str = "python", copy: bool = True, out: str = "", note_html: str = "") -> str:
    bar = (f'<div class="ui-codewin__bar"><span class="ui-codewin__dots" aria-hidden="true"><i></i><i></i><i></i></span>'
           f'<span class="ui-codewin__name">{esc(name)}</span>'
           + ('<button class="ui-codewin__copy" data-ui-copy>Copy</button>' if copy else "") + "</div>")
    return (f'<div class="ui-codewin">{bar}<pre><code class="language-{esc(lang)}">{esc(code)}</code></pre>'
            + (f'<pre class="ui-codewin__out"><code>{esc(out)}</code></pre>' if out else "")
            + (f'<p class="ui-codewin__note">{note_html}</p>' if note_html else "") + "</div>")


def callout(label: str, body_html: str, tone: str = "info") -> str:
    return f'<div class="ui-callout ui-callout--{esc(tone)}"><p class="ui-callout__label">{esc(label)}</p>{body_html}</div>'


def table(columns, rows_html) -> str:
    """`rows_html` is a list of rows, each a list of cell HTML strings."""
    head = "".join(f"<th>{esc(str(c))}</th>" for c in columns)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows_html)
    return f'<div class="ui-docsite__tablewrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def hbars(items, width: str = "420px") -> str:
    """items = [(label, value in 0..1)]: a fixed 0-1 scale, so bars are comparable across pages."""
    rows = "".join(
        f'<div class="ui-hbars__row"><span class="ui-hbars__label">{esc(str(l))}</span><div class="ui-hbars__track">'
        f'<div class="ui-hbars__fill" style="width:{max(0.0, min(1.0, float(v))) * 100:.0f}%"></div></div>'
        f'<span class="ui-hbars__value">{float(v):.2f}</span></div>' for l, v in items)
    return f'<div class="ui-hbars" style="max-width:{width};margin:10px 0">{rows}</div>'


def tier(t: str) -> str:
    return f'<ui-tier tier="{esc(t)}"></ui-tier>'


def api(name: str) -> str:
    """A dotted name the builder links to the API reference if it documents it."""
    return f'<code class="api">{esc(name)}</code>'


def empty(text_html: str) -> str:
    return f'<div class="ui-empty">{text_html}</div>'


def pkgcard(href: str, title: str, desc: str, *, meta: str = "", foot_start: str = "", foot_end: str = "", icon_html: str = "", id_: str = "") -> str:
    return f"""<a class="ui-pkgcard" href="{esc(href)}"{f' id="{esc(id_)}"' if id_ else ''}>
      <div class="ui-pkgcard__grid" aria-hidden="true"></div>
      <div class="ui-pkgcard__top">{f'<span class="ui-pkgcard__icon">{icon_html}</span>' if icon_html else '<span></span>'}<span class="ui-pkgcard__ver">{esc(meta)}</span></div>
      <h3 class="ui-pkgcard__title">{esc(title)}</h3>
      <p class="ui-pkgcard__desc">{esc(desc)}</p>
      {f'<div class="ui-pkgcard__foot"><span>{esc(foot_start)}</span><span>{esc(foot_end)}</span></div>' if foot_start or foot_end else ''}
    </a>"""


STORIES = "<!--docs-site:stories-->"
"""Put this in a plugin page's html where that page's stories should be rendered."""
