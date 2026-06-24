#!/usr/bin/env python3
"""Generate the Powered by PyREUser3 SVG cards."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

REPOSITORY = os.environ.get("PYREUSER3_REPOSITORY", "dzxrly/PyREUser3")
API_ROOT = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
OUTPUT_DIR = Path(os.environ.get("PYREUSER3_CARD_OUTPUT_DIR", "."))
LEGACY_OUTPUT = os.environ.get("PYREUSER3_CARD_OUTPUT")
FALLBACK_DESCRIPTION = "Pure Python tools for converting RE Engine .user.3 files to and from JSON."
USER_AGENT = "PyREUser3-branding-card-generator"

THEMES: Dict[str, Dict[str, str]] = {
    "dark": {
        "bg": "#0B1020",
        "border": "#263248",
        "header_a": "#102033",
        "header_b": "#132A2D",
        "header_c": "#1B2237",
        "panel": "#111827",
        "panel_border": "#25324A",
        "text": "#F8FAFC",
        "muted": "#94A3B8",
        "body": "#CBD5E1",
        "logo_bg": "#162235",
        "logo_border": "#34D399",
        "logo_text": "#E5FFF4",
        "chip_bg": "#111827",
        "chip_border": "#25324A",
        "footer": "#94A3B8",
        "link": "#E2E8F0",
        "shadow": "#020617",
    },
    "light": {
        "bg": "#F8FAFC",
        "border": "#CBD5E1",
        "header_a": "#E0F2FE",
        "header_b": "#DCFCE7",
        "header_c": "#FEF3C7",
        "panel": "#FFFFFF",
        "panel_border": "#D8E1EC",
        "text": "#0F172A",
        "muted": "#64748B",
        "body": "#475569",
        "logo_bg": "#ECFDF5",
        "logo_border": "#10B981",
        "logo_text": "#064E3B",
        "chip_bg": "#FFFFFF",
        "chip_border": "#D8E1EC",
        "footer": "#64748B",
        "link": "#0F172A",
        "shadow": "#E2E8F0",
    },
}

ACCENTS = {
    "language": "#38BDF8",
    "stars": "#FACC15",
    "forks": "#A78BFA",
    "issues": "#FB7185",
    "license": "#34D399",
}

GENERATED_OUTPUTS: Tuple[Tuple[str, str, str], ...] = (
    ("powered-by-pyreuser3.svg", "card", "dark"),
    ("powered-by-pyreuser3-dark.svg", "card", "dark"),
    ("powered-by-pyreuser3-light.svg", "card", "light"),
    ("powered-by-pyreuser3-simple.svg", "simple", "dark"),
    ("powered-by-pyreuser3-simple-dark.svg", "simple", "dark"),
    ("powered-by-pyreuser3-simple-light.svg", "simple", "light"),
)


def build_headers(token: Optional[str]) -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def request_json(path: str, token: Optional[str]) -> Dict[str, Any]:
    request = urllib.request.Request(f"{API_ROOT}{path}", headers=build_headers(token))
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def request_image(url: str, token: Optional[str]) -> Tuple[bytes, str]:
    headers = {"Accept": "image/*", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        content_type = response.headers.get_content_type() or "image/png"
        return response.read(), content_type


def fallback_repository() -> Dict[str, Any]:
    return {
        "full_name": REPOSITORY,
        "description": FALLBACK_DESCRIPTION,
        "stargazers_count": 0,
        "forks_count": 0,
        "open_issues_count": 0,
        "license": {"spdx_id": "MIT"},
        "language": "Python",
        "html_url": f"https://github.com/{REPOSITORY}",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "owner": {},
    }


def load_repository(strict: bool, offline: bool) -> Dict[str, Any]:
    if offline:
        return fallback_repository()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    try:
        return request_json(f"/repos/{REPOSITORY}", token)
    except (OSError, urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as error:
        if strict:
            print(f"Failed to fetch GitHub repository metadata: {error}", file=sys.stderr)
            raise SystemExit(1) from error
        print(f"Warning: using fallback repository metadata: {error}", file=sys.stderr)
        return fallback_repository()


def avatar_url_for_size(url: str, size: int = 128) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}s={size}"


def load_avatar_data_uri(repo: Dict[str, Any], strict: bool, offline: bool) -> Optional[str]:
    if offline:
        return None

    owner = repo.get("owner") or {}
    avatar_url = owner.get("avatar_url")
    if not isinstance(avatar_url, str) or not avatar_url:
        return None

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    try:
        data, content_type = request_image(avatar_url_for_size(avatar_url), token)
    except (OSError, urllib.error.HTTPError, urllib.error.URLError) as error:
        if strict:
            print(f"Failed to fetch GitHub avatar: {error}", file=sys.stderr)
            raise SystemExit(1) from error
        print(f"Warning: using fallback P3 mark because avatar fetch failed: {error}", file=sys.stderr)
        return None

    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def compact_count(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "0"

    if number >= 1_000_000:
        formatted = f"{number / 1_000_000:.1f}m"
    elif number >= 1_000:
        formatted = f"{number / 1_000:.1f}k"
    else:
        return str(number)
    return formatted.replace(".0", "")


def wrap_text(text: str, limit: int = 76, max_lines: int = 2) -> List[str]:
    words = text.split()
    if not words:
        return [FALLBACK_DESCRIPTION]

    lines: List[str] = []
    current = ""
    consumed_words = 0
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= limit:
            current = candidate
            consumed_words += 1
            continue

        if current:
            lines.append(current)
        current = word
        consumed_words += 1
        if len(lines) >= max_lines - 1:
            break

    if current and len(lines) < max_lines:
        lines.append(current)

    if consumed_words < len(words) and lines:
        lines[-1] = lines[-1].rstrip(" .,;:") + "..."
    return lines[:max_lines]


def format_timestamp(value: Any) -> str:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        except ValueError:
            pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def repo_fields(repo: Dict[str, Any]) -> Dict[str, str]:
    license_info = repo.get("license") or {}
    return {
        "full_name": str(repo.get("full_name") or REPOSITORY),
        "description": str(repo.get("description") or FALLBACK_DESCRIPTION),
        "language": str(repo.get("language") or "Python"),
        "license": str(license_info.get("spdx_id") or "NOASSERTION"),
        "stars": compact_count(repo.get("stargazers_count")),
        "forks": compact_count(repo.get("forks_count")),
        "issues": compact_count(repo.get("open_issues_count")),
        "updated_at": format_timestamp(repo.get("updated_at")),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "url": str(repo.get("html_url") or f"https://github.com/{REPOSITORY}"),
    }


def frame_defs(
    theme_name: str,
    width: int,
    height: int,
    header_height: int,
    accent_y: int,
    full_gradient: bool = False,
    show_accent: bool = True,
) -> str:
    theme = THEMES[theme_name]
    fill = f"url(#header-{theme_name})" if full_gradient else theme["bg"]
    header = ""
    if not full_gradient:
        header = f'''
  <path d="M1 18C1 8.611 8.611 1 18 1H{width - 18}C{width - 8.611} 1 {width - 1} 8.611 {width - 1} 18V{header_height}H1V18Z" fill="url(#header-{theme_name})"/>'''
    accent = ""
    if show_accent:
        accent = f'''
  <path d="M40 {accent_y}H{width - 40}" stroke="url(#accent-{theme_name})" stroke-width="2" stroke-linecap="round"/>'''

    return f'''  <defs>
    <linearGradient id="header-{theme_name}" x1="0" y1="0" x2="{width}" y2="0" gradientUnits="userSpaceOnUse">
      <stop stop-color="{theme['header_a']}"/>
      <stop offset="0.48" stop-color="{theme['header_b']}"/>
      <stop offset="1" stop-color="{theme['header_c']}"/>
    </linearGradient>
    <linearGradient id="accent-{theme_name}" x1="40" y1="{accent_y}" x2="{width - 40}" y2="{accent_y}" gradientUnits="userSpaceOnUse">
      <stop stop-color="#38BDF8"/>
      <stop offset="0.45" stop-color="#34D399"/>
      <stop offset="1" stop-color="#FACC15"/>
    </linearGradient>
    <filter id="soft-shadow-{theme_name}" x="-8%" y="-12%" width="116%" height="130%" color-interpolation-filters="sRGB">
      <feDropShadow dx="0" dy="8" stdDeviation="10" flood-color="{theme['shadow']}" flood-opacity="0.18"/>
    </filter>
  </defs>
  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="18" fill="{fill}" stroke="{theme['border']}"/>{header}{accent}'''


def avatar_or_mark(x: int, y: int, size: int, radius: int, theme_name: str, clip_id: str, avatar_data_uri: Optional[str]) -> str:
    theme = THEMES[theme_name]
    if avatar_data_uri:
        return f'''  <clipPath id="{clip_id}">
    <rect x="{x}" y="{y}" width="{size}" height="{size}" rx="{radius}"/>
  </clipPath>
  <rect x="{x}" y="{y}" width="{size}" height="{size}" rx="{radius}" fill="{theme['logo_bg']}" stroke="{theme['logo_border']}"/>
  <image x="{x}" y="{y}" width="{size}" height="{size}" href="{escape(avatar_data_uri)}" clip-path="url(#{clip_id})" preserveAspectRatio="xMidYMid slice"/>
  <rect x="{x}" y="{y}" width="{size}" height="{size}" rx="{radius}" fill="none" stroke="{theme['logo_border']}"/>'''

    center_x = x + size // 2
    center_y = y + int(size * 0.64)
    font_size = max(14, int(size * 0.42))
    return f'''  <rect x="{x}" y="{y}" width="{size}" height="{size}" rx="{radius}" fill="{theme['logo_bg']}" stroke="{theme['logo_border']}"/>
  <text x="{center_x}" y="{center_y}" text-anchor="middle" fill="{theme['logo_text']}" font-family="Segoe UI, Arial, sans-serif" font-size="{font_size}" font-weight="800">P3</text>'''


def metric_chip(x: int, width: int, label: str, value: str, accent: str, theme_name: str) -> str:
    theme = THEMES[theme_name]
    return f'''
  <g transform="translate({x} 176)">
    <rect width="{width}" height="31" rx="8" fill="{theme['chip_bg']}" stroke="{theme['chip_border']}"/>
    <rect width="4" height="31" rx="2" fill="{accent}"/>
    <text x="14" y="20" fill="{theme['muted']}" font-family="Segoe UI, Arial, sans-serif" font-size="10" font-weight="700">{escape(label)}</text>
    <text x="{width - 12}" y="20" text-anchor="end" fill="{theme['text']}" font-family="Segoe UI, Arial, sans-serif" font-size="13" font-weight="700">{escape(value)}</text>
  </g>'''


def render_card(repo: Dict[str, Any], theme_name: str, avatar_data_uri: Optional[str]) -> str:
    theme = THEMES[theme_name]
    fields = repo_fields(repo)
    desc_lines = wrap_text(fields["description"])
    if len(desc_lines) == 1:
        desc_lines.append("")

    chips = "".join(
        [
            metric_chip(40, 116, "Stars", fields["stars"], ACCENTS["stars"], theme_name),
            metric_chip(168, 116, "Forks", fields["forks"], ACCENTS["forks"], theme_name),
            metric_chip(296, 126, "Issues", fields["issues"], ACCENTS["issues"], theme_name),
            metric_chip(434, 286, "License", fields["license"], ACCENTS["license"], theme_name),
        ]
    )

    frame = frame_defs(theme_name, width=760, height=230, header_height=72, accent_y=72)
    avatar = avatar_or_mark(58, 109, 38, 8, theme_name, f"avatar-card-{theme_name}", avatar_data_uri)

    return f'''<svg width="760" height="230" viewBox="0 0 760 230" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">
  <title id="title">Powered by PyREUser3</title>
  <desc id="desc">GitHub repository card for {escape(fields['full_name'])}.</desc>
{frame}
  <text x="40" y="43" fill="{theme['text']}" font-family="Segoe UI, Arial, sans-serif" font-size="27" font-weight="800">Powered by PyREUser3</text>
  <text x="720" y="42" text-anchor="end" fill="{theme['muted']}" font-family="Segoe UI, Arial, sans-serif" font-size="13" font-weight="700">GitHub repository card</text>
  <rect x="40" y="92" width="680" height="70" rx="10" fill="{theme['panel']}" stroke="{theme['panel_border']}" filter="url(#soft-shadow-{theme_name})"/>
{avatar}
  <text x="114" y="119" fill="{theme['text']}" font-family="Segoe UI, Arial, sans-serif" font-size="19" font-weight="800">{escape(fields['full_name'])}</text>
  <text x="114" y="141" fill="{theme['body']}" font-family="Segoe UI, Arial, sans-serif" font-size="13">{escape(desc_lines[0])}</text>
  <text x="114" y="157" fill="{theme['body']}" font-family="Segoe UI, Arial, sans-serif" font-size="13">{escape(desc_lines[1])}</text>
{chips}
  <text x="40" y="221" fill="{theme['footer']}" font-family="Segoe UI, Arial, sans-serif" font-size="11">Updated {escape(fields['updated_at'])} | Generated {escape(fields['generated_at'])}</text>
  <text x="720" y="221" text-anchor="end" fill="{theme['link']}" font-family="Segoe UI, Arial, sans-serif" font-size="11" font-weight="700">{escape(fields['url'])} -&gt;</text>
</svg>
'''


def simple_pill(x: int, label: str, value: str, width: int, accent: str, theme_name: str) -> str:
    theme = THEMES[theme_name]
    return f'''
  <g transform="translate({x} 56)">
    <rect width="{width}" height="24" rx="7" fill="{theme['chip_bg']}" stroke="{theme['chip_border']}"/>
    <circle cx="13" cy="12" r="4" fill="{accent}"/>
    <text x="24" y="16" fill="{theme['muted']}" font-family="Segoe UI, Arial, sans-serif" font-size="10" font-weight="700">{escape(label)}</text>
    <text x="{width - 10}" y="16" text-anchor="end" fill="{theme['text']}" font-family="Segoe UI, Arial, sans-serif" font-size="12" font-weight="800">{escape(value)}</text>
  </g>'''


def simple_value_pill(x: int, value: str, width: int, accent: str, theme_name: str) -> str:
    theme = THEMES[theme_name]
    return f'''
  <g transform="translate({x} 56)">
    <rect width="{width}" height="24" rx="7" fill="{theme['chip_bg']}" stroke="{theme['chip_border']}"/>
    <circle cx="14" cy="12" r="4" fill="{accent}"/>
    <text x="28" y="16" fill="{theme['text']}" font-family="Segoe UI, Arial, sans-serif" font-size="12" font-weight="800">{escape(value)}</text>
  </g>'''


def simple_license_text(license_id: str) -> str:
    if license_id.upper() == "MIT":
        return "MIT License"
    return f"{license_id} License"


def render_simple(repo: Dict[str, Any], theme_name: str, avatar_data_uri: Optional[str]) -> str:
    theme = THEMES[theme_name]
    fields = repo_fields(repo)
    frame = frame_defs(theme_name, width=520, height=96, header_height=96, accent_y=95, full_gradient=True, show_accent=False)
    avatar = avatar_or_mark(22, 18, 46, 11, theme_name, f"avatar-simple-{theme_name}", avatar_data_uri)
    return f'''<svg width="520" height="96" viewBox="0 0 520 96" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">
  <title id="title">Powered by PyREUser3</title>
  <desc id="desc">Compact GitHub repository card for {escape(fields['full_name'])}.</desc>
{frame}
{avatar}
  <text x="84" y="34" fill="{theme['text']}" font-family="Segoe UI, Arial, sans-serif" font-size="20" font-weight="800">Powered by PyREUser3</text>
  <text x="84" y="51" fill="{theme['body']}" font-family="Segoe UI, Arial, sans-serif" font-size="12" font-weight="700">{escape(fields['full_name'])}</text>
{simple_pill(84, "Stars", fields['stars'], 90, ACCENTS['stars'], theme_name)}
{simple_pill(186, "Forks", fields['forks'], 90, ACCENTS['forks'], theme_name)}
{simple_value_pill(288, simple_license_text(fields['license']), 196, ACCENTS['license'], theme_name)}
</svg>
'''


def output_specs() -> Iterable[Tuple[Path, str, str]]:
    if LEGACY_OUTPUT:
        yield Path(LEGACY_OUTPUT), "card", "dark"
        return

    for filename, variant, theme_name in GENERATED_OUTPUTS:
        yield OUTPUT_DIR / filename, variant, theme_name


def render_variant(repo: Dict[str, Any], variant: str, theme_name: str, avatar_data_uri: Optional[str]) -> str:
    if variant == "card":
        return render_card(repo, theme_name, avatar_data_uri)
    if variant == "simple":
        return render_simple(repo, theme_name, avatar_data_uri)
    raise ValueError(f"Unknown SVG variant: {variant}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate PyREUser3 powered-by SVG cards.")
    parser.add_argument("--strict", action="store_true", help="Fail instead of using fallback metadata if the GitHub API request fails.")
    parser.add_argument("--offline", action="store_true", help="Generate with built-in fallback metadata and skip the GitHub API request.")
    args = parser.parse_args()

    repo = load_repository(strict=args.strict, offline=args.offline)
    avatar_data_uri = load_avatar_data_uri(repo, strict=args.strict, offline=args.offline)
    written: List[Path] = []
    for path, variant, theme_name in output_specs():
        svg = render_variant(repo, variant, theme_name, avatar_data_uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(svg, encoding="utf-8", newline="\n")
        written.append(path)

    for path in written:
        print(f"Wrote {path}")
    print(f"Generated {len(written)} SVG file(s) for {repo.get('full_name') or REPOSITORY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())