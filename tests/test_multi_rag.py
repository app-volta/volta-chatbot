from hashlib import sha256
from pathlib import Path
import subprocess
import sys

import httpx
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
import pytest

from app.ai.multi_rag import FederatedRag
from app.core.config import Settings


class FakeEmbeddings(Embeddings):
    def _vector(self, text: str) -> list[float]:
        digest = sha256(text.encode("utf-8")).digest()
        return [byte / 255 for byte in digest[:8]]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class ConstantEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 1.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 1.0]


def test_qdrant_backend_ingests_and_retrieves_with_the_configured_embeddings(tmp_path):
    settings = Settings(
        _env_file=None,
        rag_base_path=str(tmp_path / "faiss"),
        qdrant_url=":memory:",
        qdrant_collection_prefix="test-volta",
    )
    rag = FederatedRag(settings, embeddings=ConstantEmbeddings())

    indexed = rag.ingest_documents(
        "history",
        [Document(page_content="Procedimento de segregação do papelão.", metadata={"title": "manual", "tenant_id": "tenant-a"})],
    )
    citations = rag.retrieve("history", "segregação do papelão", tenant_id="tenant-a")

    assert indexed == 1
    assert citations
    assert citations[0].title == "manual"
    assert rag._qdrant.collection_exists("test-volta_history")

    assert rag.retrieve("history", "segregação do papelão", tenant_id="tenant-b") == []


def test_ingest_directory_persists_and_deduplicates_chunks(tmp_path):
    source = tmp_path / "documentos"
    source.mkdir()
    (source / "manual.md").write_text(
        "Plastic multilayer contaminated must remain segregated for technical evaluation.",
        encoding="utf-8",
    )
    settings = Settings(_env_file=None, rag_base_path=str(tmp_path / "faiss"), qdrant_url=None)
    rag = FederatedRag(settings, embeddings=FakeEmbeddings())

    first = rag.ingest_directory("operational", source)
    second = rag.ingest_directory("operational", source)
    citations = rag.retrieve(
        "operational",
        "Plastic multilayer contaminated must remain segregated for technical evaluation.",
    )
    script = f"""
from hashlib import sha256
from langchain_core.embeddings import Embeddings
from app.ai.multi_rag import FederatedRag
from app.core.config import Settings

class FreshEmbeddings(Embeddings):
    def _vector(self, text):
        return [byte / 255 for byte in sha256(text.encode('utf-8')).digest()[:8]]
    def embed_documents(self, texts):
        return [self._vector(text) for text in texts]
    def embed_query(self, text):
        return self._vector(text)

rag = FederatedRag(Settings(_env_file=None, rag_base_path={str(tmp_path / 'faiss')!r}, qdrant_url=None), embeddings=FreshEmbeddings())
citations = rag.retrieve('operational', 'Plastic multilayer contaminated must remain segregated for technical evaluation.')
assert citations and citations[0].title == 'manual'
"""
    fresh_process = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
    )

    assert first == 1
    assert second == 0
    assert citations
    assert citations[0].title == "manual"
    assert fresh_process.returncode == 0, fresh_process.stderr
    assert (tmp_path / "faiss" / "operational" / "index.faiss").exists()
    assert (tmp_path / "faiss" / "operational" / "index.json").exists()
    assert not (tmp_path / "faiss" / "operational" / "index.pkl").exists()
    assert (tmp_path / "faiss" / "operational" / "manifest.json").exists()


def test_ingest_directory_rejects_missing_directory(tmp_path):
    rag = FederatedRag(Settings(_env_file=None, rag_base_path=str(tmp_path / "faiss"), qdrant_url=None), embeddings=FakeEmbeddings())

    with pytest.raises(ValueError):
        rag.ingest_directory("operational", tmp_path / "missing")


def test_ingest_external_url_preserves_traceable_source(monkeypatch, tmp_path):
    response = httpx.Response(
        200,
        text="ODS 12 promove consumo e producao responsaveis. " * 30,
        request=httpx.Request("GET", "https://sdgs.un.org/goals/goal12"),
    )

    monkeypatch.setattr("app.ai.multi_rag.httpx.get", lambda *args, **kwargs: response)
    rag = FederatedRag(
        Settings(_env_file=None, rag_base_path=str(tmp_path / "faiss"), qdrant_url=None),
        embeddings=ConstantEmbeddings(),
    )

    indexed = rag.ingest_external_url(
        "regulatory",
        "https://sdgs.un.org/goals/goal12",
        "ODS 12",
    )
    citations = rag.retrieve("regulatory", "consumo e producao responsaveis")

    assert indexed >= 1
    assert citations
    assert citations[0].title == "ODS 12"
    assert citations[0].url == "https://sdgs.un.org/goals/goal12"


def test_ingest_external_url_rejects_http(tmp_path):
    rag = FederatedRag(
        Settings(_env_file=None, rag_base_path=str(tmp_path / "faiss"), qdrant_url=None),
        embeddings=ConstantEmbeddings(),
    )

    with pytest.raises(ValueError, match="HTTPS"):
        rag.ingest_external_url("regulatory", "http://sdgs.un.org/goals/goal12", "ODS 12")


def test_ingest_external_url_rejects_unknown_redirect(monkeypatch, tmp_path):
    response = httpx.Response(
        200,
        text="conteudo oficial suficiente para a ingestao. " * 30,
        request=httpx.Request("GET", "https://example.com/redirected"),
    )
    monkeypatch.setattr("app.ai.multi_rag.httpx.get", lambda *args, **kwargs: response)
    rag = FederatedRag(
        Settings(_env_file=None, rag_base_path=str(tmp_path / "faiss"), qdrant_url=None),
        embeddings=ConstantEmbeddings(),
    )

    with pytest.raises(ValueError, match="redirecionamento"):
        rag.ingest_external_url("regulatory", "https://sdgs.un.org/goals/goal12", "ODS 12")
