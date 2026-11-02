import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from app.core.auth import get_observability_access
from app.core.config import Settings, get_settings
from app.db.models import SourceCitation
from app.main import db_mongo, db_postgres, health, liveness, metrics


def test_internal_marker_survives_the_real_checkpoint_serializer():
    citation = SourceCitation(source_id="private", title="manual privado", corpus="operational", internal_document=True)
    serde = JsonPlusSerializer(allowed_msgpack_modules=[("app.db.models", "SourceCitation")])
    restored = serde.loads_typed(serde.dumps_typed(citation))
    assert restored.internal_document is True
    legacy = SourceCitation.model_validate({"source_id": "old", "title": "volta", "corpus": "operational"})
    assert legacy.internal_document is True


def test_metrics_rejects_customer_credentials_and_accepts_operator_key():
    server = FastAPI()
    server.add_api_route("/metrics", metrics)
    server.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, observability_api_key="operator-test-key")
    with TestClient(server) as client:
        assert client.get("/metrics").status_code == 401
        assert client.get("/metrics", headers={"Authorization": "Bearer customer-jwt"}).status_code == 401
        assert client.get("/metrics", headers={"Authorization": "Bearer operator-test-key"}).status_code == 200


def test_missing_operational_configuration_fails_closed():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        get_observability_access(None, Settings(_env_file=None, observability_api_key=None))
    assert error.value.status_code == 503


@pytest.mark.parametrize("postgres,mongo,expected", [(True, True, 200), (False, True, 503), (True, False, 503)])
def test_readiness_reports_dependency_health(monkeypatch, postgres, mongo, expected):
    monkeypatch.setattr(db_postgres, "healthcheck", lambda: postgres)
    monkeypatch.setattr(db_mongo, "healthcheck", lambda: mongo)
    server = FastAPI()
    server.add_api_route("/health", health)
    server.add_api_route("/health/ready", health)
    server.add_api_route("/health/live", liveness)
    with TestClient(server) as client:
        assert client.get("/health").status_code == expected
        assert client.get("/health/ready").status_code == expected
        assert client.get("/health/live").status_code == 200
