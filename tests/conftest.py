import pytest

from atlas import api


@pytest.fixture(autouse=True)
def _no_sign_in(monkeypatch):
    """Endpoint tests call the API directly; tests/test_auth.py turns sign-in back on."""
    monkeypatch.setattr(api, "AUTH", False)
