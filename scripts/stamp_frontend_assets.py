#!/usr/bin/env python3
"""根据 Vite manifest 或 git hash 统一写入 frontend/index.html 的静态资源版本。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "frontend" / "index.html"
MANIFEST_CANDIDATES = (
    ROOT / "static" / "dist" / ".vite" / "manifest.json",
    ROOT / "static" / "dist" / "manifest.json",
)
ENTRY_KEY = "static/js/app.entry.js"
SOURCE_CSS = "/static/css/app.css"
SOURCE_JS = "/static/js/app.js"
STYLESHEET_RE = re.compile(
    r'(<link\b[^>]*\brel=["\']stylesheet["\'][^>]*\bhref=["\'])([^"\']+)(["\'])',
    re.IGNORECASE,
)
MODULE_SCRIPT_RE = re.compile(
    r'(<script\b[^>]*\btype=["\']module["\'][^>]*\bsrc=["\'])([^"\']+)(["\'])',
    re.IGNORECASE,
)


def resolve_git_hash() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        value = (result.stdout or "").strip()
        if value:
            return value
    except (OSError, subprocess.CalledProcessError):
        pass
    return "dev"


def load_manifest() -> dict | None:
    for path in MANIFEST_CANDIDATES:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload:
            return payload
    return None


def resolve_dist_assets(manifest: dict) -> tuple[str, str]:
    entry = manifest.get(ENTRY_KEY)
    if not isinstance(entry, dict):
        # Vite may key by basename depending on config; fall back to first entry chunk.
        for key, value in manifest.items():
            if not isinstance(value, dict) or not value.get("isEntry") or not value.get("file"):
                continue
            key_text = str(key)
            name = str(value.get("name") or "")
            if key_text.endswith("app.entry.js") or key_text.endswith("app.js") or name in {"app", "app.entry"}:
                entry = value
                break
        if not isinstance(entry, dict):
            for value in manifest.values():
                if isinstance(value, dict) and value.get("isEntry") and value.get("file"):
                    entry = value
                    break
    if not isinstance(entry, dict) or not entry.get("file"):
        raise RuntimeError(f"Vite manifest 缺少入口 {ENTRY_KEY}")

    js_href = f"/static/dist/{str(entry['file']).lstrip('/')}"
    css_files = entry.get("css") if isinstance(entry.get("css"), list) else []
    if css_files:
        css_href = f"/static/dist/{str(css_files[0]).lstrip('/')}"
    else:
        # Fallback: pick first css asset in manifest.
        css_href = SOURCE_CSS
        for value in manifest.values():
            file_name = str((value or {}).get("file") or "")
            if file_name.endswith(".css"):
                css_href = f"/static/dist/{file_name.lstrip('/')}"
                break
    return css_href, js_href


def resolve_source_assets(version: str) -> tuple[str, str]:
    suffix = f"?v={version}"
    return f"{SOURCE_CSS}{suffix}", f"{SOURCE_JS}{suffix}"


def stamp_index(css_href: str, js_href: str) -> None:
    raw = INDEX_PATH.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    html = raw.decode("utf-8")
    if not STYLESHEET_RE.search(html):
        raise RuntimeError("frontend/index.html 未找到 stylesheet link")
    if not MODULE_SCRIPT_RE.search(html):
        raise RuntimeError("frontend/index.html 未找到 type=module script")

    html, css_count = STYLESHEET_RE.subn(rf"\g<1>{css_href}\g<3>", html, count=1)
    html, js_count = MODULE_SCRIPT_RE.subn(rf"\g<1>{js_href}\g<3>", html, count=1)
    if css_count != 1 or js_count != 1:
        raise RuntimeError("写入 index.html 资源路径失败")
    INDEX_PATH.write_bytes(html.replace("\r\n", "\n").replace("\n", newline).encode("utf-8"))
    print(f"stamped css={css_href}")
    print(f"stamped js={js_href}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        action="store_true",
        help="强制使用源码路径 + git hash，忽略 Vite dist",
    )
    args = parser.parse_args()

    if not args.source:
        manifest = load_manifest()
        if manifest is not None:
            css_href, js_href = resolve_dist_assets(manifest)
            stamp_index(css_href, js_href)
            return 0

    version = resolve_git_hash()
    css_href, js_href = resolve_source_assets(version)
    stamp_index(css_href, js_href)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
