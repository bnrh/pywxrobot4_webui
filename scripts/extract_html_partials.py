#!/usr/bin/env python3
"""Extract tab/modal HTML fragments from frontend/index.html into JS partial modules."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "frontend" / "index.html"
OUT_DIR = ROOT / "static" / "js" / "partials"

# 1-based inclusive line ranges from the monolithic index.html
PANEL_RANGES = {
    "dashboard": (73, 75),
    "messages": (77, 87),
    "users": (89, 96),
    "features": (98, 105),
    "ai-assistant": (107, 154),
    "plugins": (156, 163),
    "plugin-logs": (165, 179),
    "settings": (181, 237),
    "logs": (239, 278),
}
MODAL_RANGE = (283, 384)


def js_string(html: str) -> str:
    return html.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")


def write_partial(name: str, html: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    content = (
        f"/** Auto-extracted panel/modal fragment: {name} */\n\n"
        f"export const html = `{js_string(html.rstrip())}\\n`;\n"
    )
    (OUT_DIR / f"{name}.js").write_text(content, encoding="utf-8", newline="\n")
    print(f"wrote {name}.js ({len(html)} chars)")


def slice_lines(lines: list[str], start: int, end: int) -> str:
    return "".join(lines[start - 1 : end])


def main() -> None:
    lines = INDEX.read_text(encoding="utf-8").splitlines(keepends=True)
    for name, (start, end) in PANEL_RANGES.items():
        write_partial(name, slice_lines(lines, start, end))
    write_partial("modals", slice_lines(lines, *MODAL_RANGE))


if __name__ == "__main__":
    main()
