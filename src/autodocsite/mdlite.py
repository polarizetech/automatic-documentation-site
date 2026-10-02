"""A small Markdown renderer: enough for docstrings, READMEs and docs/*.md, stdlib only.

Handles headings, paragraphs, bullet and numbered lists (nested by indent), pipe tables, fenced
and indented code, block quotes, and inline code / bold / italic / links. Anything it does not
recognise is rendered as escaped text, so a docstring can never inject markup.
"""
from __future__ import annotations

import html
import re

_esc = html.escape


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"<[^>]+>", "", s).lower()).strip("-")


def inline(s: str) -> str:
    codes = []

    def keep(m):
        codes.append(f"<code>{_esc(m.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    s = re.sub(r"`([^`]+)`", keep, s)
    s = _esc(s, quote=False)
    s = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;[^)]*&quot;|\s+\"[^)]*\")?\)", _image, s)
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", lambda m: f'<a href="{_link(m.group(2))}">{m.group(1)}</a>', s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"(?<![\w_])_(?!\s)([^_]+?)(?<!\s)_(?![\w_])", r"<em>\1</em>", s)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], s)


#: Set by the builder per document: href -> the href to write (a generated page, a copied
#: asset, or the file on GitHub). None keeps the link as written.
LINKER = None
#: Set by the builder per document: image src -> the src to write (assets are copied into the site).
IMAGER = None


def _link(href):
    if href.startswith(("http://", "https://", "#", "mailto:")):
        return _esc(href)
    if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", href):   # any other scheme (javascript:, data:, file:) is dropped
        return "#"
    return _esc(LINKER(href) if LINKER else href)


def _image(m):
    src = m.group(2)
    if not src.startswith(("http://", "https://", "data:")) and IMAGER:
        src = IMAGER(src)
    return f'<img src="{_esc(src)}" alt="{_esc(m.group(1))}" loading="lazy" style="max-width:100%">' if src else _esc(m.group(1))


def render(md: str, *, toc: bool = False, drop_h1: bool = False):
    lines = md.replace("\t", "    ").splitlines()
    out, heads = [], []
    i = 0

    def para(buf):
        if buf:
            out.append(f"<p>{inline(' '.join(l.strip() for l in buf))}</p>")

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1
            continue
        if re.fullmatch(r"</?(p|div|br|hr|center|picture|source|img|a|details|summary|sub|sup|h\d)\b[^>]*>(\s*</?\w+[^>]*>)*", s, re.I) \
                or s.startswith("<!--"):
            i += 1          # layout-only HTML and comments: nothing a reader of the text needs
            continue
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):
            out.append("<hr>")
            i += 1
            continue
        if s.startswith("```"):
            lang = s[3:].strip()
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            code = "\n".join(lines[i + 1:j])
            out.append(f'<div class="ui-codewin"><pre><code class="language-{_esc(lang or "text")}">{_esc(_dedent(code))}</code></pre></div>')
            i = j + 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", s)
        if m:
            lvl = len(m.group(1))
            if lvl == 1 and drop_h1:
                i += 1
                continue
            text = inline(m.group(2))
            hid = _slug(m.group(2))
            heads.append((min(lvl, 3), hid, re.sub(r"<[^>]+>", "", text)))
            out.append(f'<h{min(lvl + (0 if lvl > 1 else 1), 4)} id="{hid}">{text}</h{min(lvl + (0 if lvl > 1 else 1), 4)}>')
            i += 1
            continue
        if s.startswith("|") and i + 1 < len(lines) and re.match(r"^\|?\s*:?-{2,}", lines[i + 1].strip()):
            head = _cells(s)
            j = i + 2
            rows = []
            while j < len(lines) and lines[j].strip().startswith("|"):
                rows.append(_cells(lines[j].strip()))
                j += 1
            out.append('<div class="ui-docsite__tablewrap"><table><thead><tr>' + "".join(f"<th>{inline(c)}</th>" for c in head)
                       + "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows)
                       + "</tbody></table></div>")
            i = j
            continue
        if s.startswith(">"):
            j = i
            buf = []
            while j < len(lines) and lines[j].strip().startswith(">"):
                buf.append(lines[j].strip()[1:].strip())
                j += 1
            out.append(f"<blockquote>{render(chr(10).join(buf))}</blockquote>")
            i = j
            continue
        if re.match(r"^([-*+]|\d+[.)])\s+", s):
            html_list, i = _list(lines, i)
            out.append(html_list)
            continue
        if line.startswith("    "):
            j = i
            while j < len(lines) and (lines[j].startswith("    ") or not lines[j].strip()):
                j += 1
            out.append(f'<div class="ui-codewin"><pre><code>{_esc(_dedent(chr(10).join(lines[i:j])).rstrip())}</code></pre></div>')
            i = j
            continue
        buf = []
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,6}\s|```|\||>|([-*+]|\d+[.)])\s)", lines[i].strip()):
            buf.append(lines[i])
            i += 1
        if not buf:  # a line that only looked like a block start (e.g. a lone '|'): keep it as text
            buf.append(lines[i])
            i += 1
        para(buf)
    body = "\n".join(out)
    return (body, heads) if toc else body


def _dedent(s):
    import textwrap
    return textwrap.dedent(s)


def _cells(row):
    row = row.strip().strip("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", row)]


def _list(lines, i):
    """Nested bullet/numbered list starting at lines[i]; returns (html, next_index)."""
    base = len(lines[i]) - len(lines[i].lstrip())
    ordered = bool(re.match(r"^\s*\d+[.)]\s", lines[i]))
    items = []
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            # a blank line ends the list unless the next line continues it
            if i + 1 < len(lines) and re.match(r"^\s*([-*+]|\d+[.)])\s+", lines[i + 1]) and \
                    len(lines[i + 1]) - len(lines[i + 1].lstrip()) >= base:
                i += 1
                continue
            break
        ind = len(line) - len(line.lstrip())
        m = re.match(r"^\s*([-*+]|\d+[.)])\s+(.*)", line)
        if m and ind == base:
            items.append([m.group(2), []])
            i += 1
        elif m and ind > base:
            sub, i = _list(lines, i)
            items[-1][1].append(sub)
        elif ind > base and items:
            items[-1][0] += " " + line.strip()
            i += 1
        else:
            break
    tag = "ol" if ordered else "ul"
    return f"<{tag}>" + "".join(f"<li>{inline(t)}{''.join(sub)}</li>" for t, sub in items) + f"</{tag}>", i
