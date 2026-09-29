"""MCP server exposing read-only tools for external environmental norms."""

from mcp.server.fastmcp import FastMCP

from app.ai.norms_catalog import detail_norm, search_norms

mcp = FastMCP(
    "VOLTA Environmental Norms",
    instructions=(
        "Pesquisa e detalha atos do catálogo público do Ministério do Meio Ambiente. "
        "Os resultados são informativos e não substituem validação jurídica ou técnica."
    ),
)


@mcp.tool()
def buscar_normas_residuos(termo: str, ano: int | None = None, assunto: str | None = None, limite: int = 5) -> dict:
    """Busca atos ambientais por palavras-chave na ementa, assunto ou título."""
    return search_norms(termo, year=ano, subject=assunto, limit=limite)


@mcp.tool()
def detalhar_norma(document_key: str) -> dict:
    """Retorna o registro completo de uma norma usando o document_key de uma busca."""
    return detail_norm(document_key)


if __name__ == "__main__":
    mcp.run(transport="stdio")
