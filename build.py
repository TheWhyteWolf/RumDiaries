#!/usr/bin/env python3
"""Build *The Rum Diaries*.

Fetches the campaign notes from a public Google Doc (plain-text export) and
renders each session as a parchment "letter", complete with ink splats and
rum stains, into ``site/`` ready for GitHub Pages.

Pure standard library — no third-party dependencies — so it runs anywhere
Python 3.9+ is installed and needs nothing extra in CI.
"""

from __future__ import annotations

import html
import re
import shutil
import sys
import urllib.request
from pathlib import Path

# The friend's campaign log. Must be shared as "Anyone with the link can view"
# for the plain-text export endpoint to work without authentication.
DOC_ID = "1IXuGIE9JmxElwjQeMroamQAxxFNabCJnaugU-eQgF6c"
EXPORT_URL = f"https://docs.google.com/document/d/{DOC_ID}/export?format=txt"

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
OUT = ROOT / "site"

SESSION_RE = re.compile(r"^Session\s+(\d+)\s*:?\s*(.*)$", re.IGNORECASE)
LABEL_RE = re.compile(r"^[A-Za-z][^:]{0,28}:")
BULLET_RE = re.compile(r"^\s*[-*•]\s+(.*)$")


# --------------------------------------------------------------------------- #
# Fetch + parse
# --------------------------------------------------------------------------- #
def fetch_text() -> str:
    """Download the doc as UTF-8 text with normalised line endings."""
    req = urllib.request.Request(EXPORT_URL, headers={"User-Agent": "RumDiaries/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    text = raw.decode("utf-8-sig")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def split_sessions(text: str):
    """Return (doc_title, [session dicts]).

    Everything before the first ``Session N`` line is treated as preamble; the
    first non-empty preamble line becomes the document title.
    """
    title = None
    sessions: list[dict] = []
    current: dict | None = None

    for line in text.split("\n"):
        m = SESSION_RE.match(line.strip())
        if m:
            current = {
                "num": m.group(1),
                "heading": line.strip().rstrip(":").strip() or f"Session {m.group(1)}",
                "lines": [],
            }
            sessions.append(current)
            continue
        if current is None:
            if line.strip() and not title:
                title = line.strip()
            continue
        current["lines"].append(line)

    return (title or "The Rum Diaries"), sessions


def to_blocks(lines: list[str]) -> list[list[str]]:
    """Group lines into paragraph blocks separated by blank line(s)."""
    blocks: list[list[str]] = []
    buf: list[str] = []
    for ln in lines:
        if ln.strip():
            buf.append(ln.rstrip())
        elif buf:
            blocks.append(buf)
            buf = []
    if buf:
        blocks.append(buf)
    return blocks


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #
def esc(s: str) -> str:
    return html.escape(s.strip())


def is_manifest(block: list[str]) -> bool:
    """A short opening block of ``Label: value`` lines (the session roster)."""
    if not (1 <= len(block) <= 6):
        return False
    hits = sum(1 for ln in block if LABEL_RE.match(ln))
    return hits >= max(1, (len(block) + 1) // 2)


def render_manifest(block: list[str]) -> str:
    rows = []
    for ln in block:
        if ":" in ln:
            label, _, val = ln.partition(":")
            rows.append(
                '<div class="manifest-row">'
                f'<span class="manifest-label">{esc(label)}</span>'
                f'<span class="manifest-val">{esc(val.strip(" :"))}</span>'
                "</div>"
            )
        else:
            rows.append(f'<div class="manifest-row"><span class="manifest-val">{esc(ln)}</span></div>')
    return '<aside class="manifest">' + "".join(rows) + "</aside>"


def render_block(block: list[str]) -> str:
    """Render a paragraph block, grouping consecutive bullet lines into lists."""
    out: list[str] = []
    para: list[str] = []
    items: list[str] = []

    def flush_para():
        if para:
            out.append("<p>" + esc(" ".join(para)) + "</p>")
            para.clear()

    def flush_list():
        if items:
            out.append("<ul>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>")
            items.clear()

    for ln in block:
        m = BULLET_RE.match(ln)
        if m:
            flush_para()
            items.append(m.group(1))
        else:
            flush_list()
            para.append(ln)
    flush_para()
    flush_list()
    return "".join(out)


def render_body(session: dict) -> str:
    blocks = to_blocks(session["lines"])
    parts: list[str] = []
    for i, block in enumerate(blocks):
        if i == 0 and is_manifest(block):
            parts.append(render_manifest(block))
        else:
            parts.append(render_block(block))
    if not parts:
        parts.append('<p class="faded">The ink trails off here — this tale is yet to be written&hellip;</p>')
    return "\n        ".join(parts)


def render_letter(session: dict, index: int) -> str:
    # Deterministic, gentle variety so the stack looks hand-scattered.
    tilt = (-1.1, 1.3, -0.7, 0.9, -1.4, 0.6)[index % 6]
    variant = index % 3
    body = render_body(session)
    return f"""\
      <article class="letter" id="session-{session['num']}" data-variant="{variant}" style="--tilt: {tilt}deg;">
        <div class="splat splat-1" aria-hidden="true"></div>
        <div class="splat splat-2" aria-hidden="true"></div>
        <div class="stain-ring" aria-hidden="true"></div>
        <h2 class="session-title">{esc(session['heading'])}</h2>
        {body}
      </article>"""


def render_page(title: str, sessions: list[dict]) -> str:
    letters = "\n".join(render_letter(s, i) for i, s in enumerate(sessions))
    nav = "\n".join(
        f'          <li><a href="#session-{s["num"]}">'
        f'{esc(s["heading"])}</a></li>'
        for s in sessions
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(title)} — a Pathfinder voyage, as recorded in the ship's log.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=IM+Fell+English:ital@0;1&amp;family=IM+Fell+English+SC&amp;family=Pirata+One&amp;display=swap" rel="stylesheet">
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div class="voyage">
    <header class="ledger-head">
      <h1>{esc(title)}</h1>
      <p class="subtitle">A Pathfinder voyage, as set down in the ship&rsquo;s log</p>
      <nav class="voyage-log" aria-label="Sessions">
        <span class="voyage-log-title">Ports of call</span>
        <ol>
{nav}
        </ol>
      </nav>
    </header>

    <main>
{letters}
    </main>

    <footer class="colophon">
      <p>Transcribed from the crew&rsquo;s own log &middot; these pages redraw themselves whenever the log is updated.</p>
    </footer>
  </div>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    try:
        text = fetch_text()
    except Exception as exc:  # noqa: BLE001 — surface any fetch failure clearly
        print(f"error: could not fetch the Google Doc: {exc}", file=sys.stderr)
        print("hint: the doc must be shared as 'Anyone with the link can view'.", file=sys.stderr)
        return 1

    title, sessions = split_sessions(text)
    if not sessions:
        print("error: no 'Session N:' headings found in the document.", file=sys.stderr)
        return 1

    OUT.mkdir(exist_ok=True)
    (OUT / "index.html").write_text(render_page(title, sessions), encoding="utf-8")
    shutil.copyfile(STATIC / "style.css", OUT / "style.css")

    print(f"built {len(sessions)} session(s) → {OUT / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
