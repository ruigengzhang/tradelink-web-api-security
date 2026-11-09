from contextlib import closing

import pytest

from tradelink import create_app
from tradelink.db import DEMO_PASSWORD, connect, create_schema, seed_demo


@pytest.fixture(scope="session")
def seeded_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("fixtures") / "seed.sqlite3"
    with closing(connect(path)) as db:
        create_schema(db)
        seed_demo(db)
    return path


@pytest.fixture
def app(tmp_path, seeded_db):
    path = tmp_path / "test.sqlite3"
    path.write_bytes(seeded_db.read_bytes())
    return create_app({"TESTING": True, "DATABASE": str(path)})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def sign_in(client):
    def login(username="pacific-buyer"):
        result = client.post(
            "/api/auth/login", json={"username": username, "password": DEMO_PASSWORD}
        )
        assert result.status_code == 200
        return {"Authorization": "Bearer " + result.json["access_token"]}

    return login
