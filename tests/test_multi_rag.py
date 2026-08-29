from hashlib import sha256

import httpx
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


def test_ingest_directory_persists_and_deduplicates_chunks(tmp_path):
    source = tmp_path / "documentos"
    source.mkdir()
    (source / "manual.md").write_text(
        "Plastic multilayer contaminated must remain segregated for technical evaluation.",
        encoding="utf-8",
    )
    settings = Settings(rag_base_path=str(tmp_path / "faiss"))
    rag = FederatedRag(settings, embeddings=FakeEmbeddings())

    first = rag.ingest_directory("operational", source)
    second = rag.ingest_directory("operational", source)
    citations = rag.retrieve(
        "operational",
        "Plastic multilayer contaminated must remain segregated for technical evaluation.",
    )

    assert first == 1
    assert second == 0
    assert citations
    assert citations[0].title == "manual"
    assert (tmp_path / "faiss" / "operational" / "index.faiss").exists()
    assert (tmp_path / "faiss" / "operational" / "manifest.json").exists()


def test_ingest_directory_rejects_missing_directory(tmp_path):
    rag = FederatedRag(Settings(rag_base_path=str(tmp_path / "faiss")), embeddings=FakeEmbeddings())

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
        Settings(rag_base_path=str(tmp_path / "faiss")),
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
        Settings(rag_base_path=str(tmp_path / "faiss")),
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
        Settings(rag_base_path=str(tmp_path / "faiss")),
        embeddings=ConstantEmbeddings(),
    )

    with pytest.raises(ValueError, match="redirecionamento"):
        rag.ingest_external_url("regulatory", "https://sdgs.un.org/goals/goal12", "ODS 12")
