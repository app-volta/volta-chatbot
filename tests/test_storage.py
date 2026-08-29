from app.db.storage import PostgresRepository


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

    rows = repository.consultar_metricas_esg(8, 2026, "1")

    assert rows[0]["total_waste_kg"] == 155.5
    assert "FROM esg_metric" in repository.pool.cursor.sql
    assert repository.pool.cursor.params == ("2026-08", 1, 1)


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

    rows = repository.consultar_performance_cooperativas("1")

    assert rows[0]["cooperative_name"] == "Cooperativa Recicla SP"
    assert "FROM collection" in repository.pool.cursor.sql
    assert repository.pool.cursor.params == (1, 1)


def test_non_numeric_tenant_does_not_query_shared_schema():
    repository = PostgresRepository()
    repository.pool = FakePool([])

    assert repository.consultar_metricas_esg(8, 2026, "jbs-demo") == []
    assert repository.pool.cursor.sql == ""
