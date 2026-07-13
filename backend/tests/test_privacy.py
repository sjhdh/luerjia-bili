from backend.app.services.privacy import anonymize_author, sanitize_text


def test_sanitize_text_redacts_personal_identifiers() -> None:
    text = sanitize_text(
        "联系 QQ:12345678，邮箱 test@example.com，手机 13800138000 "
        "https://x.test，回复 @某位玩家-01"
    )
    assert "12345678" not in text
    assert "test@example.com" not in text
    assert "13800138000" not in text
    assert "https://" not in text
    assert "某位玩家" not in text
    assert "[用户名已隐藏]" in text


def test_author_hash_is_stable_and_salted() -> None:
    assert anonymize_author("小明", "job-a") == anonymize_author("小明", "job-a")
    assert anonymize_author("小明", "job-a") != anonymize_author("小明", "job-b")
