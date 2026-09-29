import asyncio

import pytest

from mcp.shared.memory import create_connected_server_and_client_session

from app.ai import norms_catalog
from app.ai.agents import _call_norms_mcp, _norm_citations
from app.ai.mcp_server import mcp


def test_norms_mcp_tools_search_and_detail(monkeypatch):
    rows = [{
        "ANO": "2024",
        "DOCUMENTO": "RESOLUÇÃO",
        "Nº ": "12",
        "ATO NORMATIVO": "Resolução MMA nº 12, de 2024",
        "EMENTA": "Estabelece regras para resíduo de papelão reciclável.",
        "ÁREA MMA": "MMA",
        "ASSUNTO": "RESÍDUOS SÓLIDOS",
        "LINK": "https://www.gov.br/mma/legislacao/12",
        "STATUS": "VIGENTE",
        "REVOGA": "",
    }]
    monkeypatch.setattr(norms_catalog, "_load_catalog", lambda: (rows, "2026-09-23"))

    async def list_tools():
        async with create_connected_server_and_client_session(mcp) as session:
            listed = await session.list_tools()
            return [item.name for item in listed.tools]

    names = asyncio.run(list_tools())
    assert {"buscar_normas_residuos", "detalhar_norma"}.issubset(names)

    result = _call_norms_mcp(
        "buscar_normas_residuos",
        {"termo": "papelão", "ano": None, "assunto": None, "limite": 5},
    )
    assert result["results"][0]["status_catalogo"] == "VIGENTE"
    assert result["results"][0]["numero"] == "12"
    assert _norm_citations(result) == []

    detail = _call_norms_mcp("detalhar_norma", {"document_key": result["results"][0]["document_key"]})
    assert detail["norma"]["ato_normativo"] == "Resolução MMA nº 12, de 2024"
    citations = _norm_citations(detail)
    assert len(citations) == 1
    assert citations[0].url == "https://www.gov.br/mma/legislacao/12"


def test_catalog_download_stops_when_stream_exceeds_limit(monkeypatch):
    class MetadataResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "success": True,
                "result": {
                    "resources": [{
                        "name": "Legislação Ambiental Brasileira_2026",
                        "format": "CSV",
                        "url": "https://dados.mma.gov.br/legislacao.csv",
                        "last_modified": "2026-09-23",
                    }]
                },
            }

    class OversizedResponse:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            yield b"x" * 15_000_001

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url):
            return MetadataResponse()

        def stream(self, method, url):
            return OversizedResponse()

    monkeypatch.setattr(norms_catalog.httpx, "Client", FakeClient)
    monkeypatch.setattr(norms_catalog, "_cached_catalog", None)
    with pytest.raises(RuntimeError, match="limite de tamanho"):
        norms_catalog._load_catalog()


def test_detail_fetches_official_pdf_and_cites_its_text(monkeypatch):
    rows = [{
        "ANO": "2001",
        "DOCUMENTO": "RESOLUÇÃO",
        "Nº ": "275",
        "ATO NORMATIVO": "Resolução CONAMA nº 275/2001",
        "EMENTA": "Estabelece código de cores para diferentes tipos de resíduos.",
        "LINK": "http://conama.mma.gov.br/?option=com_sisconama&task=arquivo.download&id=273",
    }]
    monkeypatch.setattr(norms_catalog, "_load_catalog", lambda: (rows, "2026-09-23"))

    class Response:
        url = "https://conama.mma.gov.br/?option=com_sisconama&task=arquivo.download&id=273"
        headers = {"content-type": "application/pdf", "content-length": "9"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            yield b"%PDF-test"

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def stream(self, method, url):
            assert method == "GET"
            assert url.startswith("https://conama.mma.gov.br/")
            return Response()

    class Page:
        def extract_text(self):
            return "AZUL: papel e papelão. VERMELHO: plástico."

    class Reader:
        def __init__(self, stream):
            assert stream.read().startswith(b"%PDF-")
            self.pages = [Page()]

    monkeypatch.setattr(norms_catalog.httpx, "Client", Client)
    monkeypatch.setattr(norms_catalog, "PdfReader", Reader)
    record = norms_catalog._record(rows[0])
    detail = norms_catalog.detail_norm(record["document_key"])

    assert detail["norma"]["url"].startswith("https://conama.mma.gov.br/")
    assert detail["texto_integral_disponivel"] is True
    assert "AZUL: papel e papelão" in detail["texto_integral"]
    citation = _norm_citations(detail)[0]
    assert citation.url == detail["norma"]["url"]
    assert "VERMELHO: plástico" in citation.excerpt


def test_source_url_only_upgrades_allowlisted_gov_http():
    assert norms_catalog._safe_source_url("http://conama.mma.gov.br/ato") == "https://conama.mma.gov.br/ato"
    assert norms_catalog._safe_source_url("http://example.com/ato") is None
    assert norms_catalog._safe_source_url("https://conama.mma.gov.br:8443/ato") is None
