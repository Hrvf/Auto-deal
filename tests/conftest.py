import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db as dbmod
from app.security import login_limiter

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def database(tmp_path):
    url = os.getenv("TEST_DATABASE_URL")  # ex. postgresql+psycopg://… pour tester sur PostgreSQL
    if url:
        dbmod.configure(url)
        dbmod.Base.metadata.drop_all(bind=dbmod.engine)
    else:
        dbmod.configure(f"sqlite:///{tmp_path / 'test.db'}")
    dbmod.init_db()
    login_limiter._failures.clear()
    yield dbmod
    dbmod.engine.dispose()


@pytest.fixture()
def session(database):
    s = database.SessionLocal()
    yield s
    s.close()


def csrf(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, "jeton CSRF absent de la page"
    return m.group(1)


@pytest.fixture()
def app(database):
    from app.main import create_app

    return create_app()


@pytest.fixture()
def anon(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def client(app):
    """Client connecté en tant qu'administrateur (créé via la page d'installation)."""
    with TestClient(app) as c:
        page = c.get("/installation")
        r = c.post("/installation", data={
            "csrf_token": csrf(page.text), "email": "admin@exemple.fr", "display_name": "Admin",
            "password": "motdepasse-solide", "password2": "motdepasse-solide",
        }, follow_redirects=False)
        assert r.status_code == 303
        c.csrf = csrf(c.get("/").text)
        yield c


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()
