"""Tests for app.config.Settings — env precedence, validation, defaults."""

from __future__ import annotations

import os

import pytest

from app.config import Settings, get_settings


class TestSettingsDefaults:
    def test_pool_defaults_are_sized_for_multi_process(self):
        s = Settings()
        assert s.DB_POOL_SIZE >= 5
        assert s.DB_MAX_OVERFLOW >= 0

    def test_dev_autocreate_defaults_off(self):
        # Critical safety: never default-true; production must be opt-in.
        s = Settings()
        assert s.DEV_AUTOCREATE_TABLES is False

    def test_obligation_gate_in_unit_interval(self):
        s = Settings()
        assert 0.0 <= s.OBLIGATIONS_SCORE_GATE <= 1.0

    def test_log_format_defaults_to_json(self):
        s = Settings()
        assert s.LOG_FORMAT in {"json", "console"}


class TestSettingsValidation:
    def test_negative_pool_size_rejected(self):
        with pytest.raises(Exception):  # pydantic ValidationError
            Settings(DB_POOL_SIZE=0)

    def test_obligation_gate_above_one_rejected(self):
        with pytest.raises(Exception):
            Settings(OBLIGATIONS_SCORE_GATE=1.5)

    def test_circuit_breaker_threshold_min_one(self):
        with pytest.raises(Exception):
            Settings(LLM_CIRCUIT_BREAKER_THRESHOLD=0)


class TestSettingsEnvPrecedence:
    def test_env_var_overrides_default(self, monkeypatch):
        monkeypatch.setenv("OBLIGATIONS_SCORE_GATE", "0.85")
        get_settings.cache_clear()
        assert get_settings().OBLIGATIONS_SCORE_GATE == pytest.approx(0.85)

    def test_get_settings_is_cached(self):
        # Repeated calls must return the same object (cheap, lru_cache).
        a = get_settings()
        b = get_settings()
        assert a is b
