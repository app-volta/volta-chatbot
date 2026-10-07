from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.db import storage
from app.db.storage import PostgresRepository, _company_id_from_tenant


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""
        self.params = None
        self.executions = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.sql = sql
        self.params = params
        self.executions.append((sql, params))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor

    def transaction(self):
        return self


class FakePool:
    def __init__(self, rows):
        self.cursor = FakeCursor(rows)
        self.connection_obj = FakeConnection(self.cursor)

    def connection(self):
        return self.connection_obj


class ApprovalCursor(FakeCursor):
    def __init__(self, results):
        super().__init__([])
        self.results = iter(results)
        self.current_result = None

    def execute(self, sql, params):
        super().execute(sql, params)
        self.current_result = next(self.results)

    def fetchone(self):
        return self.current_result


def _approval_repository(results, *, manager=True):
    repository = PostgresRepository()
    repository.pool = FakePool([])
    cursor = ApprovalCursor(([{"manager": 1}] if manager else [None]) + results)
    repository.pool.cursor = cursor
    repository.pool.connection_obj = FakeConnection(cursor)
    return repository


def test_metric_query_uses_remote_esg_schema_and_company_scope():
    repository = PostgresRepository()
    repository.pool = FakePool(
        [{
            "company_id": 1,
            "period": "2026-08",
            "total_waste_kg": 155.5,
            "total_recycled_kg": 120.0,
            "recycling_percentage": 77.17,
            "calculated_at": None,
        }]
    )

    tenant_id = "550e8400-e29b-41d4-a716-446655440000"
    rows = repository.consultar_metricas_esg(8, 2026, tenant_id)

    assert rows[0]["total_waste_kg"] == 155.5
    assert "FROM esg_metric" in repository.pool.cursor.sql
    assert repository.pool.cursor.params == ("2026-08", UUID(tenant_id), UUID(tenant_id))


def test_performance_query_uses_remote_collection_schema():
    repository = PostgresRepository()
    repository.pool = FakePool(
        [{
            "cooperative_name": "Cooperativa Recicla SP",
            "coletas_concluidas": 2,
            "tempo_medio_resposta_horas": 4.5,
            "taxa_conclusao_percentual": 100.0,
        }]
    )

    tenant_id = "550e8400-e29b-41d4-a716-446655440000"
    rows = repository.consultar_performance_cooperativas(tenant_id)

    assert rows[0]["cooperative_name"] == "Cooperativa Recicla SP"
    assert "FROM collection" in repository.pool.cursor.sql
    assert "taxa_conclusao_percentual" in repository.pool.cursor.sql
    assert "cumprimento_sla_percentual" not in repository.pool.cursor.sql
    assert repository.pool.cursor.params == (UUID(tenant_id), UUID(tenant_id))


def test_non_numeric_tenant_does_not_query_shared_schema():
    repository = PostgresRepository()
    repository.pool = FakePool([])

    assert repository.consultar_metricas_esg(8, 2026, "jbs-demo") == []
    assert repository.pool.cursor.sql == ""


def test_company_data_queries_fail_closed_without_tenant():
    repository = PostgresRepository()
    repository.pool = FakePool([])

    assert repository.get_incident_history_by_area(4) == []
    assert repository.get_all_drafts() == []
    assert repository.consultar_metricas_esg(8, 2026) == []
    assert repository.consultar_performance_cooperativas() == []
    assert repository.get_recent_incidents() == []
    assert repository.pool.cursor.sql == ""


def test_incident_history_applies_company_scope():
    repository = PostgresRepository()
    repository.pool = FakePool(
        [{
            "data_registro": "2026-08-01",
            "peso_total_dia": 10.0,
        }]
    )

    tenant_id = "550e8400-e29b-41d4-a716-446655440000"
    rows = repository.get_incident_history_by_area(4, tenant_id)

    assert rows[0]["peso_total_dia"] == 10.0
    assert "UPPER(i.status) = 'REGISTRADA'" in repository.pool.cursor.sql
    assert "collection_status" not in repository.pool.cursor.sql
    assert repository.pool.cursor.params == (4, UUID(tenant_id))


def test_draft_query_applies_company_scope():
    repository = PostgresRepository()
    repository.pool = FakePool([{"id": UUID("550e8400-e29b-41d4-a716-446655440001")}])

    tenant_id = "550e8400-e29b-41d4-a716-446655440000"
    rows = repository.get_all_drafts(tenant_id)

    assert rows
    assert "i.company_id" in repository.pool.cursor.sql
    assert repository.pool.cursor.params == (UUID(tenant_id), UUID(tenant_id))


def test_recent_incidents_query_applies_company_scope():
    repository = PostgresRepository()
    repository.pool = FakePool([{"employee_description": "Papelão"}])

    tenant_id = "550e8400-e29b-41d4-a716-446655440000"
    rows = repository.get_recent_incidents(limit=5, tenant_id=tenant_id)

    assert rows
    assert "company_id = %s" in repository.pool.cursor.sql
    assert repository.pool.cursor.params == (UUID(tenant_id), UUID(tenant_id), 5)


def test_draft_and_recent_queries_reject_invalid_tenant_before_database_call():
    repository = PostgresRepository()
    repository.pool = FakePool([])

    assert repository.get_all_drafts("empresa-demo") == []
    assert repository.get_recent_incidents(tenant_id="empresa-demo") == []
    assert repository.pool.cursor.sql == ""


def test_draft_approval_applies_company_scope():
    draft_id = UUID("550e8400-e29b-41d4-a716-446655440001")
    tenant_id = "550e8400-e29b-41d4-a716-446655440000"
    approver_id = UUID("550e8400-e29b-41d4-a716-446655440002")
    repository = _approval_repository([{"id": draft_id}])

    assert repository.approve_occurrence_draft(draft_id, tenant_id, approver_id) == draft_id
    manager_sql, manager_params = repository.pool.cursor.executions[0]
    update_sql, update_params = repository.pool.cursor.executions[1]
    assert "JOIN role r" in manager_sql
    assert "FOR SHARE OF u, r" in manager_sql
    assert manager_params == (approver_id, UUID(tenant_id))
    assert "company_id = %s" in update_sql
    assert "status = 'AGUARDANDO_VALIDACAO'" in update_sql
    assert "user_id <> %s" in update_sql
    assert update_params == (draft_id, UUID(tenant_id), approver_id)


def test_approval_of_already_processed_draft_is_conflict():
    draft_id = UUID("550e8400-e29b-41d4-a716-446655440001")
    tenant_id = "550e8400-e29b-41d4-a716-446655440000"
    approver_id = "550e8400-e29b-41d4-a716-446655440002"
    repository = _approval_repository([
        None,
        {"user_id": UUID("550e8400-e29b-41d4-a716-446655440003"), "status": "REGISTRADA"},
    ])

    with pytest.raises(ValueError, match="já processado"):
        repository.approve_occurrence_draft(draft_id, tenant_id, approver_id)


def test_approval_blocks_author_and_hides_other_tenant_draft():
    draft_id = UUID("550e8400-e29b-41d4-a716-446655440001")
    tenant_id = "550e8400-e29b-41d4-a716-446655440000"
    approver_id = "550e8400-e29b-41d4-a716-446655440002"

    author_repository = _approval_repository([
        None,
        {"user_id": UUID(approver_id), "status": "AGUARDANDO_VALIDACAO"},
    ])
    with pytest.raises(PermissionError, match="autor"):
        author_repository.approve_occurrence_draft(draft_id, tenant_id, approver_id)

    other_tenant_repository = _approval_repository([None, None])
    with pytest.raises(LookupError, match="não encontrado"):
        other_tenant_repository.approve_occurrence_draft(draft_id, tenant_id, approver_id)
    assert "company_id = %s" in other_tenant_repository.pool.cursor.sql


def test_approval_rechecks_current_manager_role_inside_transaction():
    repository = _approval_repository([], manager=False)

    with pytest.raises(PermissionError, match="gestor"):
        repository.approve_occurrence_draft(
            UUID("550e8400-e29b-41d4-a716-446655440001"),
            "550e8400-e29b-41d4-a716-446655440000",
            "550e8400-e29b-41d4-a716-446655440002",
        )

    assert len(repository.pool.cursor.executions) == 1


def test_tenant_uuid_is_preserved_for_remote_schema():
    tenant_id = "550e8400-e29b-41d4-a716-446655440000"

    company_id = _company_id_from_tenant(tenant_id)

    assert str(company_id) == tenant_id
    assert isinstance(company_id, UUID)


def test_user_identity_is_resolved_by_authenticated_email():
    repository = PostgresRepository()
    user_id = UUID("550e8400-e29b-41d4-a716-446655440002")
    tenant_id = UUID("550e8400-e29b-41d4-a716-446655440001")
    repository.pool = FakePool([{"user_id": user_id, "tenant_id": tenant_id, "role": "gestor"}])
    identity = repository.get_user_identity_by_email("funcionario@volta.com")

    assert identity == {"user_id": user_id, "tenant_id": tenant_id, "role": "gestor"}
    assert "JOIN role r" in repository.pool.cursor.sql
    assert repository.pool.cursor.params == ("funcionario@volta.com",)


def test_occurrence_draft_rejects_area_from_another_company():
    repository = PostgresRepository()
    repository.pool = FakePool([])

    with pytest.raises(LookupError, match="Área não encontrada"):
        repository.create_occurrence_draft(
            company_id=UUID("550e8400-e29b-41d4-a716-446655440001"),
            area_id=UUID("550e8400-e29b-41d4-a716-446655440002"),
            user_id=UUID("550e8400-e29b-41d4-a716-446655440003"),
            employee_description="Papelão no setor B",
            priority="MEDIA",
            ai_data={"report_text": "Laudo"},
        )
    assert "FROM area WHERE id = %s AND company_id = %s" in repository.pool.cursor.sql


def test_visual_analysis_id_is_persisted_as_unique_ai_report_id():
    repository = PostgresRepository()
    repository.pool = FakePool([{"id": UUID("550e8400-e29b-41d4-a716-446655440004")}])
    analysis_id = UUID("550e8400-e29b-41d4-a716-446655440005")
    generated_at = datetime(2026, 10, 6, 12, tzinfo=UTC)

    repository.create_occurrence_draft(
        company_id=UUID("550e8400-e29b-41d4-a716-446655440001"),
        area_id=UUID("550e8400-e29b-41d4-a716-446655440002"),
        user_id=UUID("550e8400-e29b-41d4-a716-446655440003"),
        employee_description="Papelão no setor B",
        priority="MEDIA",
        ai_data={"analysis_id": analysis_id, "generated_at": generated_at, "report_text": "Laudo"},
    )

    incident_params = repository.pool.cursor.executions[1][1]
    sql, params = repository.pool.cursor.executions[-1]
    assert incident_params["volume"] is None
    assert "INSERT INTO ai_report" in sql
    assert "%(analysis_id)s" in sql
    assert params["analysis_id"] == analysis_id
    assert params["generated_at"] == generated_at.replace(tzinfo=None)


def test_mongodb_srv_connection_does_not_force_direct_connection(monkeypatch):
    captured = {}

    class FakeMongoClient:
        def __init__(self, uri, **options):
            captured["uri"] = uri
            captured["options"] = options

        def get_database(self):
            return {"sessions": object(), "chat_messages": object(), "security_audit": object()}

    monkeypatch.setattr(storage, "MongoClient", FakeMongoClient)

    storage.SessionRepository().open("mongodb+srv://user:password@cluster.example.net/volta")

    assert captured["uri"].startswith("mongodb+srv://")
    assert "directConnection" not in captured["options"]


def test_mongodb_multi_host_connection_does_not_force_direct_connection(monkeypatch):
    captured = {}

    class FakeMongoClient:
        def __init__(self, uri, **options):
            captured["uri"] = uri
            captured["options"] = options

        def get_database(self):
            return {"sessions": object(), "chat_messages": object(), "security_audit": object()}

    monkeypatch.setattr(storage, "MongoClient", FakeMongoClient)

    storage.SessionRepository().open("mongodb://user:password@mongo-a.example,mongo-b.example/volta")

    assert "," in captured["uri"]
    assert "directConnection" not in captured["options"]
