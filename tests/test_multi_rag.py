from hashlib import sha256

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
