"""OpenAI message content normalization helpers."""

from __future__ import annotations

from typing import Any

from .constants import MAX_CONVERSATION_MESSAGES

def _normalize_message_content(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                if item.get("type") in {"text", "input_text", "output_text"}:
                    parts.append(str(item.get("text") or item.get("content") or "").strip())
                elif isinstance(item.get("text"), str):
                    parts.append(item["text"].strip())
            elif item not in (None, ""):
                parts.append(str(item).strip())
        return "\n".join(part for part in parts if part)
    if value in (None, ""):
        return ""
    return str(value).strip()


def _normalize_openai_request_message_content(value: Any) -> str | list[dict[str, Any]]:
    if isinstance(value, str):
        return value.strip()

    raw_items = [value] if isinstance(value, dict) else value if isinstance(value, list) else None
    if raw_items is None:
        if value in (None, ""):
            return ""
        return str(value).strip()

    normalized_parts: list[dict[str, Any]] = []
    for item in raw_items:
        if isinstance(item, dict):
            item_type = str(item.get("type") or "").strip().lower()
            text = str(item.get("text") or item.get("content") or "").strip()
            if item_type in {"text", "input_text", "output_text"}:
                if text:
                    normalized_parts.append({"type": "text", "text": text})
                continue

            image_url_payload = item.get("image_url")
            if isinstance(image_url_payload, dict):
                image_url = str(image_url_payload.get("url") or image_url_payload.get("image_url") or image_url_payload.get("src") or "").strip()
            else:
                image_url = str(image_url_payload or item.get("url") or "").strip()

            has_image_payload = item_type in {"image_url", "input_image", "output_image", "image"} or "image_url" in item
            if image_url and (has_image_payload or image_url.startswith(("http://", "https://", "data:image/"))):
                normalized_parts.append({"type": "image_url", "image_url": {"url": image_url}})
                continue

            if text:
                normalized_parts.append({"type": "text", "text": text})
            continue

        if item in (None, ""):
            continue
        text = str(item).strip()
        if text:
            normalized_parts.append({"type": "text", "text": text})

    if not normalized_parts:
        return ""
    if len(normalized_parts) == 1 and normalized_parts[0].get("type") == "text":
        return str(normalized_parts[0].get("text") or "")
    return normalized_parts


def _normalize_openai_request_messages(messages: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = _normalize_openai_request_message_content(message.get("content"))
        if not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized[-MAX_CONVERSATION_MESSAGES:]


def _normalize_message_image_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        return []

    normalized_items: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    image_candidate_keys = ("image_url", "output_image", "image", "b64_json", "base64", "data")

    def append_image_item(source: Any, media_type: Any = "", alt_text: Any = "", detail: Any = "") -> None:
        normalized_source = str(source or "").strip()
        if not normalized_source or normalized_source in seen_sources:
            return
        seen_sources.add(normalized_source)
        normalized_items.append(
            {
                "url": normalized_source,
                "media_type": str(media_type or "").strip(),
                "alt_text": str(alt_text or "").strip(),
                "detail": str(detail or "").strip(),
            }
        )

    for item in raw_items:
        if not isinstance(item, dict):
            continue

        item_type = str(item.get("type") or "").strip().lower()
        if item_type and "image" not in item_type and not any(key in item for key in image_candidate_keys):
            continue

        detail = str(item.get("detail") or "").strip()
        alt_text = str(item.get("alt_text") or item.get("alt") or item.get("caption") or item.get("text") or "").strip()
        media_type = str(item.get("mime_type") or item.get("media_type") or "").strip()

        image_url_payload = item.get("image_url")
        if isinstance(image_url_payload, dict):
            append_image_item(
                image_url_payload.get("url") or image_url_payload.get("image_url") or image_url_payload.get("src") or "",
                image_url_payload.get("mime_type") or image_url_payload.get("media_type") or media_type,
                alt_text or image_url_payload.get("alt") or image_url_payload.get("caption") or "",
                detail or image_url_payload.get("detail") or "",
            )
        elif isinstance(image_url_payload, str):
            append_image_item(image_url_payload, media_type, alt_text, detail)

        for payload_key in ("output_image", "image"):
            payload_value = item.get(payload_key)
            if isinstance(payload_value, dict):
                append_image_item(
                    payload_value.get("url") or payload_value.get("image_url") or payload_value.get("src") or "",
                    payload_value.get("mime_type") or payload_value.get("media_type") or media_type,
                    alt_text or payload_value.get("alt") or payload_value.get("caption") or "",
                    detail or payload_value.get("detail") or "",
                )
            elif isinstance(payload_value, str):
                append_image_item(payload_value, media_type, alt_text, detail)

        raw_data = item.get("data")
        if isinstance(raw_data, str) and raw_data.strip().startswith("data:image/"):
            append_image_item(raw_data.strip(), media_type, alt_text, detail)

        raw_base64 = str(item.get("b64_json") or item.get("base64") or "").strip()
        if raw_base64:
            normalized_media_type = media_type or "image/png"
            append_image_item(f"data:{normalized_media_type};base64,{raw_base64}", normalized_media_type, alt_text, detail)

        direct_url = item.get("url")
        if isinstance(direct_url, str) and ("image" in item_type or direct_url.strip().startswith("data:image/")):
            append_image_item(direct_url, media_type, alt_text, detail)

    return normalized_items

def _normalize_reasoning_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value in (None, ""):
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


