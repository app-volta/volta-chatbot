"""RAG federado com índices FAISS segregados por domínio."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import Settings
from app.models import SourceCitation

Corpus = Literal["operational", "regulatory", "cooperatives", "history"]
CORPORA: tuple[Corpus, ...] = ("operational", "regulatory", "cooperatives", "history")


class FederatedRag:
    def __init__(self, settings: Settings) -> None:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY é necessária para embeddings e RAG.")
        self.settings = settings
        self.base_path = Path(settings.rag_base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-001",
            google_api_key=settings.gemini_api_key.get_secret_value(),
        )
        self._stores: dict[Corpus, FAISS] = {}

    def _path(self, corpus: Corpus) -> Path:
        return self.base_path / corpus

    def _load(self, corpus: Corpus) -> FAISS | None:
        if corpus in self._stores:
            return self._stores[corpus]
        location = self._path(corpus)
        if not (location / "index.faiss").exists():
            return None
        store = FAISS.load_local(str(location), self.embeddings, allow_dangerous_deserialization=False)
        self._stores[corpus] = store
        return store

    def ingest_documents(self, corpus: Corpus, documents: list[Document]) -> int:
        if corpus not in CORPORA:
            raise ValueError("Corpus RAG inválido.")
        if not documents:
            return 0
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
        chunks = splitter.split_documents(documents)
        for chunk in chunks:
            content_hash = hashlib.sha256(chunk.page_content.encode("utf-8")).hexdigest()[:16]
            chunk.metadata = {
                **chunk.metadata,
                "source_id": chunk.metadata.get("source_id", content_hash),
                "corpus": corpus,
                "ingested_at": datetime.now(UTC).isoformat(),
            }
        current = self._load(corpus)
        if current:
            current.add_documents(chunks)
            store = current
        else:
            store = FAISS.from_documents(chunks, self.embeddings)
            self._stores[corpus] = store
        store.save_local(str(self._path(corpus)))
        return len(chunks)

    def retrieve(self, corpus: Corpus, query: str, k: int = 4) -> list[SourceCitation]:
        store = self._load(corpus)
        if not store:
            return []
        results = store.similarity_search_with_relevance_scores(query, k=k)
        citations: list[SourceCitation] = []
        for document, score in results:
            if score < 0.35:
                continue
            metadata = document.metadata
            citations.append(
                SourceCitation(
                    source_id=str(metadata.get("source_id", "desconhecida")),
                    title=str(metadata.get("title", metadata.get("source", "Documento sem título"))),
                    corpus=corpus,
                    location=str(metadata.get("page", metadata.get("location", ""))) or None,
                    url=metadata.get("url"),
                    score=round(float(score), 3),
                    excerpt=document.page_content[:500],
                    retrieved_at=datetime.now(UTC),
                )
            )
        return citations

    def retrieve_for_route(self, route: str, query: str) -> list[SourceCitation]:
        mapping: dict[str, tuple[Corpus, ...]] = {
            "triage": ("operational",),
            "standards": ("operational", "regulatory"),
            "performance": ("cooperatives",),
            "data": ("history",),
        }
        citations: list[SourceCitation] = []
        for corpus in mapping.get(route, ()):
            citations.extend(self.retrieve(corpus, query))
        return citations

    def ingest_external_url(self, corpus: Corpus, url: str, title: str) -> int:
        """Consome uma fonte externa por allowlist e a torna rastreável no RAG."""
        host = urlparse(url).hostname or ""
        if host not in self.settings.allowed_source_hosts:
            raise ValueError("Host não permitido para ingestão externa.")
        response = httpx.get(url, timeout=self.settings.source_download_timeout_seconds, follow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        if len(text) < 300:
            raise ValueError("A fonte externa não possui conteúdo textual suficiente para indexação.")
        source_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        return self.ingest_documents(
            corpus,
            [Document(page_content=text, metadata={"source_id": source_id, "title": title, "url": url, "location": "página web"})],
        )


def serialize_citations(citations: list[SourceCitation]) -> str:
    return json.dumps([citation.model_dump(mode="json") for citation in citations], ensure_ascii=False)
