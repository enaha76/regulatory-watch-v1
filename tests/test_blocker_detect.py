"""Tests for the multilingual blocker-page detector."""

from __future__ import annotations

import pytest

from app.ingestion.blocker_detect import is_blocker_page


@pytest.mark.parametrize("title,body", [
    ("Access Denied", "You are not authorized" * 100),
    ("Just a moment...", "Checking your browser..."),
    ("Attention Required! | Cloudflare", "Please complete the challenge."),
    ("Êtes-vous un robot?", "Veuillez patienter"),
    ("Acceso denegado", "Verificación de seguridad"),
    ("Zugriff verweigert", "Sicherheitsüberprüfung"),
    ("访问被拒绝", "请稍候"),
])
def test_blocker_titles_detected_across_languages(title, body):
    reason = is_blocker_page(body, title)
    assert reason is not None
    assert reason.startswith("title:")


def test_short_body_with_javascript_pattern_is_blocker():
    body = "Please enable JavaScript to view this site."
    assert is_blocker_page(body, "Loading") is not None


def test_long_legitimate_text_with_javascript_word_is_not_blocker():
    # A real article that mentions JavaScript shouldn't be flagged.
    body = (
        "This regulatory notice covers compliance requirements. " * 200
        + "Note that the API uses JavaScript, but the rule itself is content-agnostic."
    )
    assert is_blocker_page(body, "Compliance update") is None


def test_empty_body_flagged():
    assert is_blocker_page("", "Anything") is None  # truly empty → None
    assert is_blocker_page("short.", "Anything") == "empty_body(6c)"


def test_chinese_javascript_blocker():
    body = "请启用 javascript"
    assert is_blocker_page(body, "页面") is not None


def test_french_cookies_blocker():
    body = "Veuillez activer les cookies pour continuer."
    reason = is_blocker_page(body, "Accueil")
    assert reason and (reason.startswith("body:") or reason.startswith("empty_body"))
