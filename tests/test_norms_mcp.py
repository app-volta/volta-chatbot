import asyncio
import io
from contextlib import asynccontextmanager

import pytest

from mcp.shared.memory import create_connected_server_and_client_session
from mcp.client.session import ClientSession

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.ai import norms_catalog
from app.ai.agents import _call_norms_mcp, _norm_citations
from app.ai.mcp_server import mcp


def test_norms_mcp_network_failure_is_logged_and_degrades_to_rag(monkeypatch, caplog):
    @asynccontextmanager
    async def unavailable(_server):
        raise OSError("catalogue connection refused")
        yield

    monkeypatch.setattr(
        "app.ai.agents.create_connected_server_and_client_session",
        unavailable,
    )

    with caplog.at_level("ERROR", logger="app.ai.agents"):
        result = _call_norms_mcp("buscar_normas_residuos", {"termo": "CONAMA 275"})

    assert "indisponível" in result["error"]
    assert "RAG" in result["error"]
    assert "Norms MCP call failed" in caplog.text
    assert "Traceback" in caplog.text
    assert "CONAMA 275" not in caplog.text


def test_norms_mcp_recovers_from_transport_exception_group(monkeypatch):
    @asynccontextmanager
    async def unavailable(_server):
        raise ExceptionGroup("transport", [OSError("catalogue unavailable")])
        yield

    monkeypatch.setattr("app.ai.agents.create_connected_server_and_client_session", unavailable)

    result = _call_norms_mcp("buscar_normas_residuos", {"termo": "CONAMA 275"})

    assert "temporariamente" in result["error"]
    assert "RAG" in result["error"]


def test_norms_mcp_rejects_non_object_json_payload(monkeypatch):
    class Session:
        async def call_tool(self, *_args, **_kwargs):
            class Response:
                isError = False
                content = [type("TextBlock", (), {"text": "[]"})()]

            return Response()

    @asynccontextmanager
    async def connected(_server):
        yield Session()

    monkeypatch.setattr("app.ai.agents.create_connected_server_and_client_session", connected)

    result = _call_norms_mcp("buscar_normas_residuos", {"termo": "CONAMA 275"})

    assert "temporariamente" in result["error"]
    assert "RAG" in result["error"]


def test_norms_mcp_tools_search_and_detail(monkeypatch):
    calls = []
    original_call_tool = ClientSession.call_tool

    async def traced_call_tool(self, name, arguments=None, *args, **kwargs):
        calls.append((name, arguments))
        return await original_call_tool(self, name, arguments, *args, **kwargs)

    monkeypatch.setattr(ClientSession, "call_tool", traced_call_tool)
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
    assert [name for name, _ in calls] == ["buscar_normas_residuos", "detalhar_norma"]
    assert calls[1][1]["document_key"] == result["results"][0]["document_key"]
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

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 720 Td (AZUL papel e papelao; VERMELHO plastico.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    pdf = io.BytesIO()
    writer.write(pdf)
    pdf_bytes = pdf.getvalue()

    class Response:
        url = "https://conama.mma.gov.br/?option=com_sisconama&task=arquivo.download&id=273"
        headers = {"content-type": "application/pdf", "content-length": str(len(pdf_bytes))}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            yield pdf_bytes

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

    monkeypatch.setattr(norms_catalog.httpx, "Client", Client)
    calls = []
    original_call_tool = ClientSession.call_tool

    async def traced_call_tool(self, name, arguments=None, *args, **kwargs):
        calls.append((name, arguments))
        return await original_call_tool(self, name, arguments, *args, **kwargs)

    monkeypatch.setattr(ClientSession, "call_tool", traced_call_tool)
    result = _call_norms_mcp(
        "buscar_normas_residuos",
        {"termo": "CONAMA 275", "ano": 2001, "assunto": None, "limite": 5},
    )
    document_key = result["results"][0]["document_key"]
    detail = _call_norms_mcp("detalhar_norma", {"document_key": document_key})

    assert [name for name, _ in calls] == ["buscar_normas_residuos", "detalhar_norma"]
    assert calls[1][1]["document_key"] == document_key
    assert detail["norma"]["url"].startswith("https://conama.mma.gov.br/")
    assert detail["texto_integral_disponivel"] is True
    assert "AZUL papel e papelao" in detail["texto_integral"]
    citation = _norm_citations(detail)[0]
    assert citation.url == detail["norma"]["url"]
    assert "VERMELHO plastico" in citation.excerpt


def test_source_url_only_upgrades_allowlisted_gov_http():
    assert norms_catalog._safe_source_url("http://conama.mma.gov.br/ato") == "https://conama.mma.gov.br/ato"
    assert norms_catalog._safe_source_url("http://example.com/ato") is None
    assert norms_catalog._safe_source_url("https://conama.mma.gov.br:8443/ato") is None
