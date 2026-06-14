"""Pytest shared configuration for aiagent-comms."""
import pytest


@pytest.fixture(autouse=True)
def _no_llm_api_key(monkeypatch):
    """Regression tests run in mock/offline mode unless explicitly overridden."""
    monkeypatch.setenv("LLM_API_KEY", "")
