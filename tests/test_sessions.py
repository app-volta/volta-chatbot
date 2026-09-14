from datetime import UTC, datetime

from langchain_core.embeddings import Embeddings
from app.api.sessions import close
from app.ai.multi_rag import FederatedRag
from app.core.auth import RequestIdentity
from app.core.config import Settings


class FakeSessions:
    def __init__(self):
        self.closed = False

    def ensure_session_owner(self, session_id, tenant_id, user_id):
        assert (session_id, tenant_id, user_id) == ("session-1", "tenant-a", "user-1")

    def session_history(self, session_id):
        return [{"role": "user", "content": "Registrar papelão no setor B."}]

    def close_session(self, session_id, tenant_id, user_id):
        self.closed = True
        return datetime(2026, 9, 11, tzinfo=UTC)


class FakeTeam:
    def summarize_session(self, messages):
        return "A sessão registrou papelão no setor B."


class FakeRag:
    def __init__(self):
        self.documents = []

    def ingest_documents(self, corpus, documents):
        self.documents.append((corpus, documents))
        return 1


def test_close_session_indexes_only_the_sanitized_summary():
    sessions = FakeSessions()
    rag = FakeRag()

    response = close(
        "session-1",
        RequestIdentity(tenant_id="tenant-a", user_id="user-1"),
        sessions=sessions,
        rag=rag,
        team=FakeTeam(),
    )

    assert response.session_id == "session-1"
    assert response.summary_indexed is True
    assert sessions.closed is True
    corpus, documents = rag.documents[0]
    assert corpus == "history"
    assert documents[0].metadata["tenant_id"] == "tenant-a"
    assert documents[0].metadata["session_id"] == "session-1"


class FixedEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]


def test_closed_session_summary_round_trips_through_qdrant_per_tenant(tmp_path):
    sessions = FakeSessions()
    rag = FederatedRag(
        Settings(
            _env_file=None,
            rag_base_path=str(tmp_path / "faiss"),
            qdrant_url=":memory:",
            qdrant_collection_prefix="e2e-volta",
        ),
        embeddings=FixedEmbeddings(),
    )

    response = close(
        "session-1",
        RequestIdentity(tenant_id="tenant-a", user_id="user-1"),
        sessions=sessions,
        rag=rag,
        team=FakeTeam(),
    )

    tenant_a = rag.retrieve_for_route(
        "triage", "Qual resíduo foi registrado no setor B?", tenant_id="tenant-a"
    )
    tenant_b = rag.retrieve_for_route(
        "triage", "Qual resíduo foi registrado no setor B?", tenant_id="tenant-b"
    )

    assert response.summary_indexed is True
    assert tenant_a and tenant_a[0].excerpt == "A sessão registrou papelão no setor B."
    assert tenant_a[0].source_id == "session-1"
    assert tenant_b == []
