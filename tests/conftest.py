import pytest

from atlas import api, chat


@pytest.fixture(autouse=True)
def _no_sign_in(monkeypatch):
    """Endpoint tests call the API directly; tests/test_auth.py turns sign-in back on."""
    monkeypatch.setattr(api, "AUTH", False)


@pytest.fixture(autouse=True)
def _claude_on_path(monkeypatch):
    """Tests only build the Claude command, never run it, so they must not need the CLI installed."""
    monkeypatch.setattr(chat, "claude_bin", lambda: "claude")
