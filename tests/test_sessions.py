from datetime import UTC, datetime

from app.api.sessions import close
from app.db.models import SessionCloseRequest


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
        SessionCloseRequest(tenant_id="tenant-a", user_id="user-1"),
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

