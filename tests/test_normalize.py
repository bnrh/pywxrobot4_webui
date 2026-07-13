from utils.normalize import (
    FALSY_VALUES,
    TRUTHY_VALUES,
    collapse_whitespace,
    is_truthy,
    normalize_text,
    normalize_wxpid,
)


def test_normalize_text_strips_edges() -> None:
    assert normalize_text("  hello  ") == "hello"
    assert normalize_text(None) == ""
    assert normalize_text("") == ""


def test_collapse_whitespace_folds_internal_spaces() -> None:
    assert collapse_whitespace("  hello   world\n") == "hello world"


def test_normalize_wxpid_supports_decimal_and_hex() -> None:
    assert normalize_wxpid(12345) == 12345
    assert normalize_wxpid("12345") == 12345
    assert normalize_wxpid("0x10") == 16
    assert normalize_wxpid("") is None
    assert normalize_wxpid(None) is None
    assert normalize_wxpid(True) is None


def test_is_truthy_common_forms() -> None:
    assert is_truthy(True) is True
    assert is_truthy(False) is False
    assert is_truthy(1) is True
    assert is_truthy(0) is False
    assert is_truthy("yes") is True
    assert is_truthy("是") is True
    assert is_truthy("no") is False
    assert is_truthy("否") is False
    assert is_truthy(None) is False
    assert is_truthy(None, True) is True
    assert is_truthy("unknown") is False
    assert "true" in TRUTHY_VALUES
    assert "false" in FALSY_VALUES
