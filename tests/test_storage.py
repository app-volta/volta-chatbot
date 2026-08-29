from uuid import UUID

from app.db.storage import PostgresRepository, _company_id_from_tenant


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor


class FakePool:
    def __init__(self, rows):
        self.cursor = FakeCursor(rows)
        self.connection_obj = FakeConnection(self.cursor)

    def connection(self):
        return self.connection_obj


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
            "cumprimento_sla_percentual": 100.0,
        }]
    )

    tenant_id = "550e8400-e29b-41d4-a716-446655440000"
    rows = repository.consultar_performance_cooperativas(tenant_id)

    assert rows[0]["cooperative_name"] == "Cooperativa Recicla SP"
    assert "FROM collection" in repository.pool.cursor.sql
    assert repository.pool.cursor.params == (UUID(tenant_id), UUID(tenant_id))


def test_non_numeric_tenant_does_not_query_shared_schema():
    repository = PostgresRepository()
    repository.pool = FakePool([])

    assert repository.consultar_metricas_esg(8, 2026, "jbs-demo") == []
    assert repository.pool.cursor.sql == ""


def test_incident_history_applies_company_scope():
    repository = PostgresRepository()
    repository.pool = FakePool(
        [{"data_registro": "2026-08-01", "peso_total_dia": 10.0}]
    )

    tenant_id = "550e8400-e29b-41d4-a716-446655440000"
    rows = repository.get_incident_history_by_area(4, tenant_id)

    assert rows[0]["peso_total_dia"] == 10.0
    assert "company_id = %s" in repository.pool.cursor.sql
    assert repository.pool.cursor.params == (4, UUID(tenant_id), UUID(tenant_id))


def test_tenant_uuid_is_preserved_for_remote_schema():
    tenant_id = "550e8400-e29b-41d4-a716-446655440000"

    company_id = _company_id_from_tenant(tenant_id)

    assert str(company_id) == tenant_id
    assert isinstance(company_id, UUID)
