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
from langchain_core.embeddings import Embeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import Settings
from app.db.models import SourceCitation

Corpus = Literal["operational", "regulatory", "cooperatives", "history"]
CORPORA: tuple[Corpus, ...] = ("operational", "regulatory", "cooperatives", "history")


class FederatedRag:
    def __init__(self, settings: Settings, embeddings: Embeddings | None = None) -> None:
        if not settings.gemini_api_key and embeddings is None:
            raise RuntimeError("GEMINI_API_KEY é necessária para embeddings e RAG.")
        self.settings = settings
        self.base_path = Path(settings.rag_base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.embeddings = embeddings or GoogleGenerativeAIEmbeddings(
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

    def _manifest_path(self, corpus: Corpus) -> Path:
        return self._path(corpus) / "manifest.json"

    def _load_manifest(self, corpus: Corpus) -> set[str]:
        path = self._manifest_path(corpus)
        if not path.exists():
            return set()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return set(payload.get("chunk_ids", []))
        except (OSError, json.JSONDecodeError):
            return set()

    def _save_manifest(self, corpus: Corpus, chunk_ids: set[str]) -> None:
        self._manifest_path(corpus).write_text(
            json.dumps({"chunk_ids": sorted(chunk_ids)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def ingest_documents(self, corpus: Corpus, documents: list[Document]) -> int:
        if corpus not in CORPORA:
            raise ValueError("Corpus RAG inválido.")
        if not documents:
            return 0
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
        chunks = splitter.split_documents(documents)
        known_ids = self._load_manifest(corpus)
        new_chunks = []
        for chunk in chunks:
            source_id = str(chunk.metadata.get("source_id", chunk.metadata.get("source", "")))
            chunk_id = hashlib.sha256(
                f"{source_id}\n{chunk.page_content}".encode("utf-8")
            ).hexdigest()
            if chunk_id in known_ids:
                continue
            chunk.metadata = {
                **chunk.metadata,
                "source_id": chunk.metadata.get("source_id", chunk_id[:16]),
                "chunk_id": chunk_id,
                "corpus": corpus,
                "ingested_at": datetime.now(UTC).isoformat(),
            }
            new_chunks.append(chunk)
            known_ids.add(chunk_id)
        if not new_chunks:
            return 0
        current = self._load(corpus)
        if current:
            current.add_documents(new_chunks)
            store = current
        else:
            store = FAISS.from_documents(new_chunks, self.embeddings)
            self._stores[corpus] = store
        store.save_local(str(self._path(corpus)))
        self._save_manifest(corpus, known_ids)
        return len(new_chunks)

    def ingest_directory(self, corpus: Corpus, directory: str | Path) -> int:
        """Carrega TXT, Markdown e PDF de um diretório e indexa o corpus."""
        root = Path(directory)
        if not root.is_dir():
            raise ValueError(f"Diretório de documentos não encontrado: {root}")
        documents: list[Document] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() in {".txt", ".md", ".markdown"}:
                text = path.read_text(encoding="utf-8")
                if text.strip():
                    documents.append(Document(
                        page_content=text,
                        metadata={"source": str(path), "title": path.stem},
                    ))
            elif path.suffix.lower() == ".pdf":
                try:
                    from pypdf import PdfReader
                except ImportError as exc:
                    raise RuntimeError("Instale pypdf para ingerir documentos PDF.") from exc
                for page_number, page in enumerate(PdfReader(str(path)).pages, start=1):
                    text = page.extract_text() or ""
                    if text.strip():
                        documents.append(Document(
                            page_content=text,
                            metadata={
                                "source": str(path),
                                "title": path.stem,
                                "page": page_number,
                            },
                        ))
        return self.ingest_documents(corpus, documents)

    def retrieve(self, corpus: Corpus, query: str, k: int = 4) -> list[SourceCitation]:
        if not query.strip():
            return []
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
            # O agente de Dados usa RAG apenas para contexto e definições;
            # números e KPIs continuam vindo exclusivamente do PostgreSQL.
            "data": ("regulatory", "history"),
        }
        citations: list[SourceCitation] = []
        for corpus in mapping.get(route, ()):
            citations.extend(self.retrieve(corpus, query))
        return citations

    def ingest_external_url(self, corpus: Corpus, url: str, title: str) -> int:
        """Consome uma fonte externa por allowlist e a torna rastreável no RAG."""
        parsed_url = urlparse(url)
        host = parsed_url.hostname or ""
        if parsed_url.scheme != "https":
            raise ValueError("A fonte externa deve usar HTTPS.")
        if host not in self.settings.allowed_source_hosts:
            raise ValueError("Host não permitido para ingestão externa.")
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("O título da fonte externa é obrigatório.")
        response = httpx.get(url, timeout=self.settings.source_download_timeout_seconds, follow_redirects=True)
        response.raise_for_status()
        final_host = urlparse(str(getattr(response, "url", url))).hostname or host
        if final_host not in self.settings.allowed_source_hosts:
            raise ValueError("O redirecionamento da fonte externa não é permitido.")
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        if len(text) < 300:
            raise ValueError("A fonte externa não possui conteúdo textual suficiente para indexação.")
        source_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        return self.ingest_documents(
            corpus,
            [Document(page_content=text, metadata={"source_id": source_id, "title": clean_title, "url": url, "location": "página web"})],
        )


def serialize_citations(citations: list[SourceCitation]) -> str:
    return json.dumps([citation.model_dump(mode="json") for citation in citations], ensure_ascii=False)
