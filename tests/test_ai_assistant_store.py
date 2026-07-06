from ai_assistant_store import (
    AI_ASSISTANT_JOB_ACTIVE_STATUSES,
    AI_ASSISTANT_JOB_TERMINAL_STATUSES,
    create_ai_assistant_conversation_payload,
    ensure_ai_assistant_conversation_payload,
    now_iso,
    set_ai_assistant_job,
)


def test_ai_assistant_store_public_api_exports() -> None:
    assert callable(now_iso)
    assert callable(create_ai_assistant_conversation_payload)
    assert callable(ensure_ai_assistant_conversation_payload)
    assert callable(set_ai_assistant_job)
    assert "queued" in AI_ASSISTANT_JOB_ACTIVE_STATUSES
    assert "completed" in AI_ASSISTANT_JOB_TERMINAL_STATUSES


def test_now_iso_returns_timezone_aware_string() -> None:
    value = now_iso()
    assert "T" in value
    assert len(value) >= 19
