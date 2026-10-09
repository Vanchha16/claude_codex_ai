"""Test safety net: VC Signal is MT5-only, so every test runs with an OFFLINE fake as the app's default feed factory.

No test can reach a real MetaTrader 5 terminal (or account) through create_app()/Workstation defaults. Tests that need
market data pass an explicit test-only feed (tests/fixture_feed.py: FixtureFeed). Telegram is never configured by
default in tests (Settings() has no token)."""
import pytest

from tests.fixture_feed import FixtureFeed, OfflineFeed


@pytest.fixture(autouse=True)
def _never_touch_a_real_terminal(monkeypatch):
    import app.web as web
    monkeypatch.setattr(web, "default_feed_factory", lambda settings: OfflineFeed())
    yield


def fixture_factory(settings=None):
    """create_app(feed_factory=fixture_factory): the deterministic fictional TEST fixture presented as an MT5 feed."""
    return FixtureFeed()
