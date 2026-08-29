import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.ai.mcp_server import consultar_metricas_esg


class FakePostgresRepository:
    opened_with = None
    queried_with = None
    closed = False

    def open(self, dsn: str) -> None:
        type(self).opened_with = dsn

    def consultar_metricas_esg(self, month: int, year: int, tenant_id: str) -> list[dict]:
        type(self).queried_with = (month, year, tenant_id)
        return [{"tenant_id": tenant_id, "volume_total_kg": 12.5}]

    def close(self) -> None:
        type(self).closed = True


def test_mcp_tool_delegates_to_tenant_scoped_repository() -> None:
    settings = SimpleNamespace(postgres_url="postgresql://test")

    with patch("app.ai.mcp_server.get_settings", return_value=settings), patch(
        "app.ai.mcp_server.PostgresRepository", FakePostgresRepository
    ):
        result = consultar_metricas_esg(8, 2026, "tenant-a")

    assert json.loads(result) == [{"tenant_id": "tenant-a", "volume_total_kg": 12.5}]
    assert FakePostgresRepository.opened_with == "postgresql://test"
    assert FakePostgresRepository.queried_with == (8, 2026, "tenant-a")
    assert FakePostgresRepository.closed is True


@pytest.mark.parametrize(
    ("month", "tenant_id", "message"),
    [(0, "tenant-a", "mes"), (13, "tenant-a", "mes"), (8, "", "tenant_id")],
)
def test_mcp_tool_rejects_invalid_scope(month: int, tenant_id: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        consultar_metricas_esg(month, 2026, tenant_id)
