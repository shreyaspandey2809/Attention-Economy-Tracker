from datetime import datetime, timezone

import pytest

from attention_tracker.synthetic.archetypes import ARCHETYPES
from attention_tracker.synthetic.generator import SyntheticEventGenerator


@pytest.fixture(scope="session")
def make_events():
    gen = SyntheticEventGenerator()
    cache: dict = {}

    def _make(user_id: str, archetype: str = "DOOMSCROLLER", num_days: int = 2, start=(2026, 3, 2)):
        key = (user_id, archetype, num_days, start)
        if key not in cache:
            day = datetime(*start, tzinfo=timezone.utc)
            cache[key] = gen.generate(user_id, ARCHETYPES[archetype], day, num_days=num_days)
        return list(cache[key])

    return _make


@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient

    from attention_tracker.api.app import create_app

    app = create_app(db_path=":memory:", model_dir=tmp_path / "no_models")
    return TestClient(app)


@pytest.fixture
def issue(client):
    """issue('u1') -> auth headers for a fresh device of that user."""
    from attention_tracker.api.auth import issue_device

    def _issue(user_id: str) -> dict:
        _device_id, token = issue_device(client.app.state.repo, user_id)
        return {"Authorization": f"Bearer {token}"}

    return _issue


def payload(events) -> dict:
    return {"events": [e.model_dump(mode="json") for e in events]}
