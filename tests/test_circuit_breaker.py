"""Tests for the circuit breaker (uses fakeredis to avoid live broker)."""

from __future__ import annotations

import time

import pytest


@pytest.fixture
def fake_redis(monkeypatch):
    """Patch redis.from_url so circuit_breaker uses an in-memory fake."""
    import fakeredis

    fake = fakeredis.FakeRedis()

    def _from_url(*args, **kwargs):
        return fake

    monkeypatch.setattr("redis.from_url", _from_url)
    yield fake
    fake.flushall()


def test_breaker_starts_closed(fake_redis):
    from app.services import circuit_breaker
    assert circuit_breaker.is_open("openai:test") is False


def test_breaker_trips_after_threshold(fake_redis, monkeypatch):
    monkeypatch.setenv("LLM_CIRCUIT_BREAKER_THRESHOLD", "3")
    monkeypatch.setenv("LLM_CIRCUIT_BREAKER_WINDOW_SECONDS", "60")
    monkeypatch.setenv("LLM_CIRCUIT_BREAKER_COOLDOWN_SECONDS", "60")

    from app.config import get_settings
    get_settings.cache_clear()

    from app.services import circuit_breaker

    for _ in range(2):
        tripped = circuit_breaker.record_failure("openai:test")
        assert not tripped
        assert not circuit_breaker.is_open("openai:test")

    tripped = circuit_breaker.record_failure("openai:test")
    assert tripped is True
    assert circuit_breaker.is_open("openai:test") is True


def test_breaker_clears_on_success(fake_redis, monkeypatch):
    monkeypatch.setenv("LLM_CIRCUIT_BREAKER_THRESHOLD", "2")
    from app.config import get_settings
    get_settings.cache_clear()

    from app.services import circuit_breaker

    circuit_breaker.record_failure("openai:test")
    circuit_breaker.record_failure("openai:test")
    assert circuit_breaker.is_open("openai:test") is True

    circuit_breaker.record_success("openai:test")
    assert circuit_breaker.is_open("openai:test") is False


def test_breaker_isolation_between_scopes(fake_redis, monkeypatch):
    monkeypatch.setenv("LLM_CIRCUIT_BREAKER_THRESHOLD", "1")
    from app.config import get_settings
    get_settings.cache_clear()

    from app.services import circuit_breaker

    circuit_breaker.record_failure("scope_A")
    assert circuit_breaker.is_open("scope_A") is True
    assert circuit_breaker.is_open("scope_B") is False
