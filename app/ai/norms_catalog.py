"""Read-only search over the MMA's consolidated environmental legislation catalog."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import time
import unicodedata
from threading import Lock
from urllib.parse import urlsplit

import httpx
from pypdf import PdfReader

MMA_DATASET_URL = "https://dados.mma.gov.br/dataset/legislacao-ambiental-brasileira"
_PACKAGE_API_URL = "https://dados.mma.gov.br/api/3/action/package_show?id=legislacao-ambiental-brasileira"
_CACHE_TTL_SECONDS = 24 * 60 * 60
_MAX_DOCUMENT_BYTES = 15_000_000
_MAX_DOCUMENT_TEXT = 12_000
_cache_lock = Lock()
_cached_catalog: tuple[float, list[dict[str, str]], str] | None = None


def _normalise(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char)).replace("º", "o")


def _safe_source_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value.strip())
        hostname = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        return None
    if hostname != "gov.br" and not hostname.endswith(".gov.br"):
        return None
    if port not in {None, 80, 443}:
        return None
    return parsed._replace(scheme="https", netloc=hostname).geturl()


def _download_norm_text(url: str) -> str:
    safe_url = _safe_source_url(url)
    if not safe_url:
        return ""

    content = bytearray()
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        with client.stream("GET", safe_url) as response:
            response.raise_for_status()
            if not _safe_source_url(str(response.url)):
                return ""
            length = response.headers.get("content-length", "")
            if length.isdigit() and int(length) > _MAX_DOCUMENT_BYTES:
                return ""
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > _MAX_DOCUMENT_BYTES:
                    return ""

    if not content.startswith(b"%PDF-"):
        return ""
    text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)
    return re.sub(r"[ \t]+", " ", text).strip()[:_MAX_DOCUMENT_TEXT]


def _latest_csv(client: httpx.Client) -> tuple[str, str]:
    response = client.get(_PACKAGE_API_URL)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError("O catálogo do MMA não retornou metadados válidos.")

    resources = payload["result"].get("resources", [])
    candidates = [
        item for item in resources
        if item.get("format", "").casefold() == "csv"
        and re.search(r"_(20\d{2})$", item.get("name", ""))
        and urlsplit(item.get("url", "")).hostname == "dados.mma.gov.br"
        and urlsplit(item.get("url", "")).scheme == "https"
    ]
    if not candidates:
        raise RuntimeError("O catálogo do MMA não publicou um CSV anual disponível.")
    resource = max(candidates, key=lambda item: int(re.search(r"_(20\d{2})$", item["name"]).group(1)))
    return resource["url"], resource.get("last_modified", "")


def _load_catalog() -> tuple[list[dict[str, str]], str]:
    global _cached_catalog
    now = time.monotonic()
    with _cache_lock:
        if _cached_catalog and now - _cached_catalog[0] < _CACHE_TTL_SECONDS:
            return _cached_catalog[1], _cached_catalog[2]

        with httpx.Client(timeout=20, follow_redirects=False) as client:
            csv_url, updated_at = _latest_csv(client)
            content = bytearray()
            with client.stream("GET", csv_url) as response:
                response.raise_for_status()
                if response.headers.get("content-length", "").isdigit() and int(response.headers["content-length"]) > 15_000_000:
                    raise RuntimeError("O arquivo do catálogo excedeu o limite de tamanho permitido.")
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 15_000_000:
                        raise RuntimeError("O arquivo do catálogo excedeu o limite de tamanho permitido.")

        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("cp1252")
        rows = list(csv.DictReader(io.StringIO(text), delimiter=";"))
        if not rows:
            raise RuntimeError("O catálogo do MMA não contém registros legíveis.")
        _cached_catalog = (now, rows, updated_at)
        return rows, updated_at


def _record(row: dict[str, str]) -> dict[str, str]:
    fields = {_normalise(key.strip()): (value or "").strip() for key, value in row.items() if key}
    title = fields.get("ato normativo") or "Ato normativo sem título"
    link = _safe_source_url(fields.get("link", "")) or ""
    source_key = "|".join((title, fields.get("ano", ""), fields.get("no", ""), link))
    return {
        "document_key": hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:16],
        "ano": fields.get("ano", ""),
        "tipo": fields.get("documento", ""),
        "numero": fields.get("no", ""),
        "ato_normativo": title,
        "ementa": fields.get("ementa", ""),
        "area": fields.get("area mma", ""),
        "assunto": fields.get("assunto", ""),
        "status_catalogo": fields.get("status", ""),
        "revoga": fields.get("revoga", ""),
        "url": link or MMA_DATASET_URL,
    }


def search_norms(term: str, *, year: int | None = None, subject: str | None = None, limit: int = 5) -> dict:
    if not term.strip() or len(term) > 120:
        raise ValueError("Informe um termo de 1 a 120 caracteres.")
    if year is not None and not 1937 <= year <= 2100:
        raise ValueError("O ano precisa estar entre 1937 e 2100.")
    if subject is not None and len(subject) > 80:
        raise ValueError("O assunto pode ter no máximo 80 caracteres.")
    if not 1 <= limit <= 8:
        raise ValueError("O limite precisa estar entre 1 e 8.")

    rows, updated_at = _load_catalog()
    tokens = [token for token in _normalise(term).split() if len(token) > 1]
    if not tokens:
        raise ValueError("O termo precisa conter ao menos duas letras ou números.")
    subject_query = _normalise(subject or "").strip()
    matches: list[dict[str, str]] = []
    for raw in rows:
        item = _record(raw)
        if year is not None and item["ano"] != str(year):
            continue
        if subject_query and subject_query not in _normalise(item["assunto"]):
            continue
        haystack = _normalise(" ".join(item[key] for key in ("ato_normativo", "ementa", "assunto", "status_catalogo")))
        if all(token in haystack for token in tokens):
            matches.append(item)

    matches.sort(key=lambda item: (int(item["ano"] or 0), item["ato_normativo"]), reverse=True)
    return {
        "source": MMA_DATASET_URL,
        "catalog_updated_at": updated_at,
        "disclaimer": "O status reproduz o texto do catálogo do MMA; não confirma, por si só, vigência nem aplicabilidade ao caso.",
        "results": [
            {**item, "ementa": item["ementa"][:1000]}
            for item in matches[:limit]
        ],
    }


def detail_norm(document_key: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{16}", document_key):
        raise ValueError("Use o identificador document_key retornado pela busca.")
    rows, updated_at = _load_catalog()
    for raw in rows:
        item = _record(raw)
        if item["document_key"] == document_key:
            try:
                document_text = _download_norm_text(item["url"])
            except Exception:
                # A source outage or malformed PDF must not erase usable catalog metadata.
                document_text = ""
            return {
                "source": MMA_DATASET_URL,
                "catalog_updated_at": updated_at,
                "disclaimer": "Detalhamento informativo do catálogo do MMA; confirme vigência e aplicação com o responsável técnico/jurídico.",
                "norma": item,
                "texto_integral": document_text,
                "texto_integral_disponivel": bool(document_text),
            }
    return {"source": MMA_DATASET_URL, "catalog_updated_at": updated_at, "not_found": True}
