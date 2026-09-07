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
import time
import urllib.request
from pathlib import Path

# The friend's campaign log. Must be shared as "Anyone with the link can view"
# for the plain-text export endpoint to work without authentication.
DOC_ID = "1IXuGIE9JmxElwjQeMroamQAxxFNabCJnaugU-eQgF6c"
EXPORT_URL = f"https://docs.google.com/document/d/{DOC_ID}/export?format=txt"

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
OUT = ROOT / "site"

# A session heading is "Session N", optionally followed by a separator and a
# title. Demanding the separator keeps ordinary prose that merely opens with
# "Session 2 will be next Thursday…" from being mistaken for a new heading.
SESSION_RE = re.compile(r"^Session\s+(\d+)\s*(?:[:.–—-]\s*(.*))?$", re.IGNORECASE)

# A roster label: up to three words (parentheticals allowed) before the colon.
# Anchored loosely so indented exports still match, and word-limited so a
# narrative line like "We set out at dawn: the sea was calm" is left alone.
_LABEL_WORD = r"[A-Za-z(][A-Za-z'’&/()-]*"
LABEL_RE = re.compile(rf"^\s*[A-Za-z][A-Za-z'’&/()-]*(?:[ ]{_LABEL_WORD}){{0,2}}\s*:")

# Google Docs' text export uses a different glyph per nesting level, and
# autocorrects a typed "- " into an en dash.
BULLET_RE = re.compile(r"^\s*[-*+•·‣◦○●▪▫–—]\s+(.*)$")
NUMBER_RE = re.compile(r"^\s*\d{1,3}[.)]\s+(.*)$")

FADED_NOTE = '<p class="faded">The ink trails off here — this tale is yet to be written&hellip;</p>'


class FetchError(RuntimeError):
    """The doc could not be fetched, or what came back was not the doc."""


# --------------------------------------------------------------------------- #
# Fetch + parse
# --------------------------------------------------------------------------- #
def fetch_text(attempts: int = 3) -> str:
    """Download the doc as UTF-8 text with normalised line endings.

    Transport hiccups are retried — a scheduled build should not fail (and
    e-mail the world) because Google blinked. A response that is *not* plain
    text means the export endpoint handed us a sign-in or error page instead,
    which no amount of retrying will fix.
    """
    req = urllib.request.Request(EXPORT_URL, headers={"User-Agent": "RumDiaries/1.0"})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                final_url = resp.geturl()
                content_type = resp.headers.get_content_type()
                raw = resp.read()
        except Exception as exc:  # noqa: BLE001 — any transport failure is retryable
            if attempt == attempts:
                raise FetchError(f"could not reach the Google Doc: {exc}") from exc
            time.sleep(2 * attempt)
            continue

        if content_type != "text/plain":
            # Google answers an unshared doc with HTTP 200 and a sign-in page,
            # so without this check the failure would surface much later as a
            # baffling "no Session headings found".
            raise FetchError(
                f"the export endpoint returned {content_type} instead of plain text "
                f"(landed on {final_url}) — the doc is most likely not shared publicly"
            )

        text = raw.decode("utf-8-sig")
        return text.replace("\r\n", "\n").replace("\r", "\n")

    raise FetchError("could not reach the Google Doc")  # pragma: no cover — loop always returns


def split_sessions(text: str):
    """Return (doc_title, preamble_lines, [session dicts]).

    Everything before the first ``Session N`` line is preamble; its first
    non-empty line becomes the document title and the rest is kept for the
    header. Each session gets a unique HTML id, so a doc that repeats a
    session number (a continuation, or a typo) still yields working anchors.
    """
    title = None
    preamble: list[str] = []
    sessions: list[dict] = []
    current: dict | None = None

    for line in text.split("\n"):
        m = SESSION_RE.match(line.strip())
        if m:
            heading = line.strip()
            if heading.endswith(":"):
                heading = heading[:-1].rstrip()
            current = {"num": m.group(1), "heading": heading, "lines": []}
            sessions.append(current)
            continue
        if current is None:
            if title is None:
                if line.strip():
                    title = line.strip()
            else:
                preamble.append(line)
            continue
        current["lines"].append(line)

    seen: dict[str, int] = {}
    for session in sessions:
        base = f"session-{session['num']}"
        seen[base] = seen.get(base, 0) + 1
        session["id"] = base if seen[base] == 1 else f"{base}-{seen[base]}"

    return (title or "The Rum Diaries"), preamble, sessions


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
    """A short opening block of ``Label: value`` lines (the session roster).

    Needs at least two label lines, so a lone sentence that happens to carry a
    colon is not dressed up as a roster.
    """
    if not (2 <= len(block) <= 6):
        return False
    hits = sum(1 for ln in block if LABEL_RE.match(ln))
    return hits >= max(2, (len(block) + 1) // 2)


def render_manifest(block: list[str]) -> str:
    rows = []
    for ln in block:
        ln = ln.strip()
        if LABEL_RE.match(ln):
            label, _, val = ln.partition(":")
            rows.append(
                '<div class="manifest-row">'
                f'<span class="manifest-label">{esc(label)}</span>'
                f'<span class="manifest-val">{esc(val.strip(" :"))}</span>'
                "</div>"
            )
        else:
            # Not a label — a continuation line. Keep it whole rather than
            # chopping it at whatever colon it happens to contain.
            rows.append(f'<div class="manifest-row"><span class="manifest-val">{esc(ln)}</span></div>')
    return '<aside class="manifest">' + "".join(rows) + "</aside>"


def render_block(block: list[str]) -> str:
    """Render a paragraph block, grouping consecutive list lines into lists."""
    out: list[str] = []
    para: list[str] = []
    items: list[str] = []
    kind: str | None = None

    def flush_para():
        if para:
            out.append("<p>" + esc(" ".join(para)) + "</p>")
            para.clear()

    def flush_list():
        nonlocal kind
        if items:
            tag = kind or "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{esc(i)}</li>" for i in items) + f"</{tag}>")
            items.clear()
        kind = None

    for ln in block:
        m = BULLET_RE.match(ln)
        this_kind = "ul"
        if not m:
            m = NUMBER_RE.match(ln)
            this_kind = "ol"
        if m:
            flush_para()
            if kind and kind != this_kind:
                flush_list()
            kind = this_kind
            items.append(m.group(1))
        else:
            flush_list()
            para.append(ln)
    flush_para()
    flush_list()
    return "".join(out)


def render_content(lines: list[str], empty_note: str | None = None) -> str:
    """Render doc lines: an opening roster block, then prose and lists."""
    parts: list[str] = []
    for i, block in enumerate(to_blocks(lines)):
        if i == 0 and is_manifest(block):
            parts.append(render_manifest(block))
        else:
            parts.append(render_block(block))
    if not parts and empty_note:
        parts.append(empty_note)
    return "\n        ".join(parts)


def render_letter(session: dict, index: int) -> str:
    # Deterministic, gentle variety so the stack looks hand-scattered.
    tilt = (-1.1, 1.3, -0.7, 0.9, -1.4, 0.6)[index % 6]
    variant = index % 3
    body = render_content(session["lines"], FADED_NOTE)
    return f"""\
      <article class="letter" id="{session['id']}" data-variant="{variant}" style="--tilt: {tilt}deg;">
        <div class="splat splat-1" aria-hidden="true"></div>
        <div class="splat splat-2" aria-hidden="true"></div>
        <div class="stain-ring" aria-hidden="true"></div>
        <h2 class="session-title">{esc(session['heading'])}</h2>
        {body}
      </article>"""


def render_page(title: str, preamble: list[str], sessions: list[dict]) -> str:
    letters = "\n".join(render_letter(s, i) for i, s in enumerate(sessions))
    nav = "\n".join(
        f'          <li><a href="#{s["id"]}">'
        f'{esc(s["heading"])}</a></li>'
        for s in sessions
    )
    intro = render_content(preamble)
    intro_html = f'\n      <div class="preamble">\n        {intro}\n      </div>' if intro else ""
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
      <p class="subtitle">A Pathfinder voyage, as set down in the ship&rsquo;s log</p>{intro_html}
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
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print("hint: the doc must be shared as 'Anyone with the link can view'.", file=sys.stderr)
        return 1

    title, preamble, sessions = split_sessions(text)
    if not sessions:
        print("error: no 'Session N:' headings found in the document.", file=sys.stderr)
        return 1

    style_src = STATIC / "style.css"
    if not style_src.is_file():
        print(f"error: missing stylesheet: {style_src}", file=sys.stderr)
        return 1

    page = render_page(title, preamble, sessions)
    try:
        OUT.mkdir(exist_ok=True)
        shutil.copyfile(style_src, OUT / "style.css")
        (OUT / "index.html").write_text(page, encoding="utf-8")
    except OSError as exc:
        print(f"error: could not write the site: {exc}", file=sys.stderr)
        return 1

    print(f"built {len(sessions)} session(s) → {OUT / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
