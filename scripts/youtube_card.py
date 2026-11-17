#!/usr/bin/env python3
"""
Refresh the YouTube parts of the profile README.

What it does (run by .github/workflows/youtube.yml every few hours):
  1. Reads the channel's public RSS feed  -> no API key needed.
  2. Writes assets/youtube-latest-{dark,light}.svg -> animated "latest upload" card
     (transparent background, one version per GitHub theme),
     with the thumbnail embedded in base64 (an SVG shown through <img>
     on GitHub is not allowed to load external images, so we inline it).
  3. Rewrites the block between <!-- YOUTUBE:START --> and <!-- YOUTUBE:END -->
     in README.md with clickable thumbnails of the latest videos.

Only the Python standard library is used, so the workflow needs no pip install.

Usage:
  YT_CHANNEL_ID=UCxxxxxxxx python scripts/youtube_card.py
  python scripts/youtube_card.py --feed-file feed.xml   # offline test
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"  # writes youtube-latest-dark.svg + youtube-latest-light.svg
README_PATH = ROOT / "README.md"
VIDEOS_IN_README = 3

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}
FONT = "-apple-system,BlinkMacSystemFont,'SF Pro Display','Inter','Segoe UI',Helvetica,Arial,sans-serif"


# ------------------------------------------------------------------ fetching
def fetch(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "profile-readme-bot"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_feed(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    videos = []
    for entry in root.findall("atom:entry", NS):
        vid = entry.findtext("yt:videoId", namespaces=NS)
        if not vid:
            continue
        stats = entry.find("media:group/media:community/media:statistics", NS)
        videos.append({
            "id": vid,
            "title": entry.findtext("atom:title", default="", namespaces=NS).strip(),
            "published": dt.datetime.fromisoformat(
                entry.findtext("atom:published", namespaces=NS).replace("Z", "+00:00")
            ),
            "views": int(stats.get("views")) if stats is not None and stats.get("views") else None,
        })
    videos.sort(key=lambda v: v["published"], reverse=True)
    return videos


def thumbnail_data_uri(video_id: str) -> str | None:
    """mqdefault = 320x180, true 16:9 (hqdefault has black bars)."""
    try:
        data = fetch(f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg")
        return "data:image/jpeg;base64," + base64.b64encode(data).decode()
    except Exception as exc:  # network hiccup -> card still renders, with a placeholder
        print(f"warning: thumbnail not fetched ({exc})", file=sys.stderr)
        return None


# ------------------------------------------------------------------ helpers
def wrap(text: str, max_chars: int, max_lines: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for w in words:
        if len(line) + len(w) + (1 if line else 0) <= max_chars:
            line = f"{line} {w}".strip()
        else:
            lines.append(line)
            line = w
        if len(lines) == max_lines:
            break
    if len(lines) < max_lines and line:
        lines.append(line)
    used = " ".join(lines)
    if len(used) < len(text.strip()):  # text was cut -> end on a whole word + ellipsis
        last = lines[-1]
        if len(last) + 1 > max_chars and " " in last:
            last = last.rsplit(" ", 1)[0]
        lines[-1] = last.rstrip(" ,.:;-—&") + "…"
    return lines or [""]


def human_views(n: int | None) -> str:
    if n is None:
        return ""
    for unit, size in (("M", 1_000_000), ("K", 1_000)):
        if n >= size:
            return f"{n / size:.1f}".rstrip("0").rstrip(".") + f"{unit} views"
    return f"{n} views"


# ------------------------------------------------------------------ rendering
# Transparent background + one variant per GitHub theme (picked with <picture> in the README)
THEMES = {
    "dark":  {"text": "#f5f5f7", "sec": "#a1a1a6", "red": "#FF453A", "blue": "#0A84FF", "link": "#2997FF"},
    "light": {"text": "#1d1d1f", "sec": "#6e6e73", "red": "#FF3B30", "blue": "#007AFF", "link": "#0066CC"},
}
EASE = "cubic-bezier(.25,.1,.25,1)"


def render_card(video: dict, thumb: str | None, now: dt.datetime, theme: str) -> str:
    t = THEMES[theme]
    W, H = 900, 240
    TX, TY, TW, TH = 20, 20, 356, 200
    CX, CY = TX + TW / 2, TY + TH / 2
    is_new = (now - video["published"]).days < 7
    title_lines = wrap(video["title"], 29, 2)  # ~14px per char at 26px bold, 460px available
    views = human_views(video["views"])
    meta = video["published"].strftime("%d %b %Y") + (f"  ·  {views}" if views else "")

    if thumb:
        picture = f'<image href="{thumb}" x="{TX}" y="{TY}" width="{TW}" height="{TH}" preserveAspectRatio="xMidYMid slice" clip-path="url(#thumb)"/>'
    else:
        picture = f'<rect x="{TX}" y="{TY}" width="{TW}" height="{TH}" fill="url(#ph)" clip-path="url(#thumb)"/>'
    title_svg = "".join(
        f'<tspan x="420" dy="{0 if i == 0 else 32}">{escape(line)}</tspan>' for i, line in enumerate(title_lines)
    )
    badge = (
        f'<rect class="up" x="420" y="38" width="48" height="22" rx="11" fill="{t["blue"]}"/>'
        f'<text class="up" x="444" y="53.5" text-anchor="middle" font-family="{FONT}" font-size="11.5" font-weight="700" fill="#fff">NEW</text>'
        if is_new else ""
    )
    eyebrow_x = 480 if is_new else 420
    meta_y = 108 + 32 * len(title_lines)

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="Latest YouTube upload: {escape(video["title"])}">
  <title>Latest upload — {escape(video["title"])}</title>
  <defs>
    <linearGradient id="ph" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0A84FF"/><stop offset=".5" stop-color="#BF5AF2"/><stop offset="1" stop-color="#FF375F"/></linearGradient>
    <clipPath id="thumb"><rect x="{TX}" y="{TY}" width="{TW}" height="{TH}" rx="16"/></clipPath>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="150%"><feDropShadow dx="0" dy="8" stdDeviation="10" flood-color="#000" flood-opacity=".25"/></filter>
  </defs>
  <style>
    .up {{ opacity:0; animation: up .9s {EASE} forwards; }}
    .d1 {{ animation-delay:.12s }} .d2 {{ animation-delay:.24s }} .d3 {{ animation-delay:.36s }}
    @keyframes up {{ from {{ opacity:0; transform: translateY(10px) }} to {{ opacity:1; transform:none }} }}
    .play {{ transform-box: fill-box; transform-origin: center; animation: breathe 2.4s ease-in-out infinite; }}
    @keyframes breathe {{ 50% {{ transform: scale(1.08) }} }}
  </style>

  <g filter="url(#shadow)"><rect x="{TX}" y="{TY}" width="{TW}" height="{TH}" rx="16" fill="#000" fill-opacity=".001"/>{picture}</g>
  <rect x="{TX}" y="{TY + TH - 4}" width="{TW}" height="4" fill="#fff" fill-opacity=".3" clip-path="url(#thumb)"/>
  <rect x="{TX}" y="{TY + TH - 4}" width="0" height="4" fill="{t["red"]}" clip-path="url(#thumb)">
    <animate attributeName="width" values="0;{TW}" dur="7s" repeatCount="indefinite"/>
  </rect>
  <g class="play">
    <circle cx="{CX}" cy="{CY}" r="30" fill="#fff" fill-opacity=".92"/>
    <polygon points="{CX - 8},{CY - 12} {CX - 8},{CY + 12} {CX + 13},{CY}" fill="{t["red"]}"/>
  </g>

  {badge}
  <text class="up" x="{eyebrow_x}" y="54" font-family="{FONT}" font-size="13" font-weight="700" letter-spacing="1.2" fill="{t["red"]}">LATEST UPLOAD</text>
  <text class="up d1" x="420" y="104" font-family="{FONT}" font-size="26" font-weight="700" letter-spacing="-.4" fill="{t["text"]}">{title_svg}</text>
  <text class="up d2" x="420" y="{meta_y}" font-family="{FONT}" font-size="15" font-weight="500" fill="{t["sec"]}">{escape(meta)}</text>
  <text class="up d3" x="420" y="{meta_y + 34}" font-family="{FONT}" font-size="16" font-weight="600" fill="{t["link"]}">Watch on YouTube ›</text>
</svg>
'''


def render_readme_block(videos: list[dict]) -> str:
    cells = []
    for v in videos[:VIDEOS_IN_README]:
        url = f"https://www.youtube.com/watch?v={v['id']}"
        title = escape(v["title"], quote=True)
        cells.append(
            f'  <a href="{url}" title="{title}">'
            f'<img src="https://i.ytimg.com/vi/{v["id"]}/mqdefault.jpg" width="260" alt="{title}"/></a>'
        )
    return '<p align="center">\n' + "\n".join(cells) + "\n</p>"


def update_readme(latest: dict, block: str) -> bool:
    text = README_PATH.read_text(encoding="utf-8")
    new = re.sub(
        r"(<!-- YOUTUBE:START -->).*?(<!-- YOUTUBE:END -->)",
        lambda m: f"{m.group(1)}\n{block}\n{m.group(2)}",
        text,
        flags=re.S,
    )
    # the animated card is wrapped in a link that must always point to the newest video
    new = re.sub(
        r'(<!-- YOUTUBE:LATEST -->.*?<a href=")[^"]*(")',
        lambda m: f"{m.group(1)}https://www.youtube.com/watch?v={latest['id']}{m.group(2)}",
        new,
        count=1,
        flags=re.S,
    )
    if new != text:
        README_PATH.write_text(new, encoding="utf-8")
        return True
    return False


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed-file", help="read the RSS from a local file instead of YouTube")
    args = ap.parse_args()

    if args.feed_file:
        xml_bytes = Path(args.feed_file).read_bytes()
    else:
        channel = os.environ.get("YT_CHANNEL_ID", "").strip()
        if not channel.startswith("UC"):
            print("error: set YT_CHANNEL_ID to your channel id (starts with 'UC')", file=sys.stderr)
            return 1
        xml_bytes = fetch(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel}")

    videos = parse_feed(xml_bytes)
    if not videos:
        print("feed is empty, nothing to update")
        return 0

    latest = videos[0]
    now = dt.datetime.now(dt.timezone.utc)
    thumb = thumbnail_data_uri(latest["id"])
    ASSETS.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        (ASSETS / f"youtube-latest-{theme}.svg").write_text(render_card(latest, thumb, now, theme), encoding="utf-8")
    changed = update_readme(latest, render_readme_block(videos))
    print(f"card updated for '{latest['title']}' · README {'updated' if changed else 'unchanged'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
