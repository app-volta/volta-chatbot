"""Servidor MCP read-only para integrações corporativas autorizadas.

Execute separadamente: python -m app.mcp_server
"""

import json

from mcp.server.fastmcp import FastMCP

from app.config import get_settings
from app.pg_tools import PostgresRepository

mcp = FastMCP("VOLTA Corporate Tools")


@mcp.tool()
def consultar_metricas_esg(mes: int, ano: int, tenant_id: str) -> str:
    """Retorna métricas ESG agregadas e somente leitura para um tenant autorizado."""
    if not 1 <= mes <= 12:
        raise ValueError("mes deve estar entre 1 e 12")
    settings = get_settings()
    repository = PostgresRepository(settings.postgres_url)
    repository.open()
    try:
        return json.dumps(repository.consultar_metricas_esg(mes, ano, tenant_id), ensure_ascii=False, default=str)
    finally:
        repository.close()


if __name__ == "__main__":
    mcp.run(transport="stdio")
