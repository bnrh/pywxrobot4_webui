"""Resolve console CSS/JS URLs for frontend/index.html."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from app_config import FRONTEND_INDEX_PAGE, STATIC_DIR

STYLESHEET_RE = re.compile(
    r'(<link\b[^>]*\brel=["\']stylesheet["\'][^>]*\bhref=["\'])([^"\']+)(["\'])',
    re.IGNORECASE,
)
MODULE_SCRIPT_RE = re.compile(
    r'(<script\b[^>]*\btype=["\']module["\'][^>]*\bsrc=["\'])([^"\']+)(["\'])',
    re.IGNORECASE,
)

MANIFEST_CANDIDATES = (
    STATIC_DIR / "dist" / ".vite" / "manifest.json",
    STATIC_DIR / "dist" / "manifest.json",
)
ENTRY_KEYS = ("static/js/app.entry.js", "static/js/app.js")


def _load_manifest() -> dict | None:
    import json

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


def _resolve_dist_assets(manifest: dict) -> tuple[str, str] | None:
    entry = None
    for key in ENTRY_KEYS:
        candidate = manifest.get(key)
        if isinstance(candidate, dict) and candidate.get("file"):
            entry = candidate
            break
    if not isinstance(entry, dict):
        for key, value in manifest.items():
            if not isinstance(value, dict) or not value.get("isEntry") or not value.get("file"):
                continue
            key_text = str(key)
            name = str(value.get("name") or "")
            if key_text.endswith("app.entry.js") or key_text.endswith("app.js") or name in {"app", "app.entry"}:
                entry = value
                break
    if not isinstance(entry, dict) or not entry.get("file"):
        return None

    js_href = f"/static/dist/{str(entry['file']).lstrip('/')}"
    css_files = entry.get("css") if isinstance(entry.get("css"), list) else []
    if css_files:
        css_href = f"/static/dist/{str(css_files[0]).lstrip('/')}"
    else:
        css_href = "/static/css/app.css"
        for value in manifest.values():
            file_name = str((value or {}).get("file") or "")
            if file_name.endswith(".css"):
                css_href = f"/static/dist/{file_name.lstrip('/')}"
                break

    js_path = STATIC_DIR / "dist" / str(entry["file"]).lstrip("/")
    if not js_path.is_file():
        return None
    return css_href, js_href


@lru_cache(maxsize=1)
def resolve_frontend_asset_hrefs() -> tuple[str, str]:
    """Prefer Vite dist when present; otherwise fall back to source modules."""
    manifest = _load_manifest()
    if manifest is not None:
        resolved = _resolve_dist_assets(manifest)
        if resolved is not None:
            return resolved
    return "/static/css/app.css", "/static/js/app.js"


def render_frontend_index_html() -> str:
    raw = Path(FRONTEND_INDEX_PAGE).read_text(encoding="utf-8")
    css_href, js_href = resolve_frontend_asset_hrefs()
    html, css_count = STYLESHEET_RE.subn(rf"\g<1>{css_href}\g<3>", raw, count=1)
    html, js_count = MODULE_SCRIPT_RE.subn(rf"\g<1>{js_href}\g<3>", html, count=1)
    if css_count != 1 or js_count != 1:
        return raw
    return html


def clear_frontend_asset_cache() -> None:
    resolve_frontend_asset_hrefs.cache_clear()
