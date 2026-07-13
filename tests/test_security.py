import pytest

from server.security import extract_bearer_token, is_public_request_path


def test_extract_bearer_token() -> None:
    assert extract_bearer_token("Bearer secret-token") == "secret-token"
    assert extract_bearer_token("Basic abc") == ""
    assert extract_bearer_token("") == ""


def test_public_request_paths() -> None:
    assert is_public_request_path("/")
    assert is_public_request_path("/health")
    assert is_public_request_path("/static/js/app.js")
    assert not is_public_request_path("/api/overview")
