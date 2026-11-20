"""Shared fixtures. Only tests marked `live` may call a real LLM or Langfuse endpoint."""

from __future__ import annotations

import os

import pytest

from adlantis.config import Settings, get_settings


@pytest.fixture(autouse=True)
def isolated_env(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Strip project env vars and run from an empty dir so a local `.env` is ignored.

    Live tests are exempt: they need the real keys from the environment or `.env`.
    """
    if request.node.get_closest_marker("live"):
        return
    for name in list(Settings.model_fields):
        monkeypatch.delenv(name.upper(), raising=False)
    for name in list(os.environ):
        if name.upper().startswith("MODEL__"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def restore_logging():
    """CLI tests call configure_logging(); undo it so later tests log normally."""
    import logging

    logger = logging.getLogger("adlantis")
    saved = (list(logger.handlers), logger.level, logger.propagate)
    yield
    logger.handlers, logger.level, logger.propagate = saved[0], saved[1], saved[2]
