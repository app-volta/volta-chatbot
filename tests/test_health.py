import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import db_mongo, db_postgres, health, liveness


@pytest.mark.parametrize("postgres,mongo,expected", [(True, True, 200), (False, True, 503), (True, False, 503)])
def test_readiness_reports_dependency_health(monkeypatch, postgres, mongo, expected):
    monkeypatch.setattr(db_postgres, "healthcheck", lambda: postgres)
    monkeypatch.setattr(db_mongo, "healthcheck", lambda: mongo)
    app = FastAPI()
    app.add_api_route("/health", health)
    app.add_api_route("/health/ready", health)
    app.add_api_route("/health/live", liveness)

    with TestClient(app) as client:
        assert client.get("/health").status_code == expected
        assert client.get("/health/ready").status_code == expected
        assert client.get("/health/live").status_code == 200
