# The Rum Diaries

Renders a pirate-themed Pathfinder campaign log — kept in a shared Google Doc —
as a stack of parchment **letters**, complete with ink splats and rum stains.

The page rebuilds itself: a GitHub Action re-fetches the doc on a schedule and
redeploys to GitHub Pages, so updates to the log appear on the site
automatically (no copy-paste).

## How it works

```
Google Doc ──(plain-text export)──▶ build.py ──▶ site/index.html ──▶ GitHub Pages
                                       ▲                                  ▲
                                  parses sessions                  hourly rebuild
                                  + parchment HTML                 via Actions
```

- **`build.py`** — fetches the doc, splits it on `Session N:` headings, and
  renders each session as a parchment letter. Pure standard library, no deps.
- **`static/style.css`** — all the parchment / ink / stain styling (no binary
  assets; textures are generated with CSS gradients + an inline SVG filter).
- **`.github/workflows/deploy.yml`** — builds and deploys, on push, hourly, or
  on demand (`workflow_dispatch`). Hourly runs fingerprint the built site and
  skip the deploy when the log hasn't changed, so an untouched doc costs one
  cheap build instead of a full republish.

## What the doc should look like

The parser is deliberately forgiving, but it keys off a few conventions:

- **`Session N: Title`** starts a new session. The colon (or a dash) matters —
  it is what separates a heading from a sentence that merely happens to open
  with "Session 2 will be next Thursday". A bare `Session 7` works too.
- **The first line of the doc** becomes the page title; anything else above the
  first session heading is rendered as an introduction under it.
- **The first block of a session** becomes the roster box when at least two of
  its lines look like `Present: …` / `Out: …`. Prose is left alone.
- **Bullets** (`-`, `*`, `•`, and the glyphs Google Docs uses for nested
  levels) become lists; `1.` / `1)` lines become numbered lists.

## Build locally

```sh
python build.py        # writes site/index.html + site/style.css
xdg-open site/index.html
```

## Deploy to GitHub Pages

1. **Share the doc:** in Google Docs, *Share → General access → Anyone with the
   link → Viewer*. (The build reads it anonymously via the export endpoint.)
2. Create a GitHub repo and push this directory to it.
3. In the repo: **Settings → Pages → Build and deployment → Source → GitHub
   Actions**.
4. Push to `main` (or run the workflow manually from the **Actions** tab). The
   site publishes at `https://<user>.github.io/<repo>/`.

## Changing things

- **Different doc:** edit `DOC_ID` at the top of `build.py`.
- **Rebuild frequency:** edit the `cron` line in `deploy.yml` (default hourly;
  it only redeploys when the rendered site actually changed).
- **Look & feel:** it's all in `static/style.css` — parchment colours live in the
  `:root` block; ink splats and stains are the `.splat` / `.stain-ring` rules.
