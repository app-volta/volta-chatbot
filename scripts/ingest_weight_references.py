"""Indexa as referências públicas de densidade no corpus de peso configurado."""

from io import BytesIO

import httpx
from langchain_core.documents import Document
from pypdf import PdfReader

from app.ai.multi_rag import FederatedRag
from app.core.config import get_settings


SOURCES = {
    "EPA EUA - Volume to Weight Conversion Factors (2016)": "https://www.epa.gov/sites/default/files/2016-04/documents/volume_to_weight_conversion_factors_memorandum_04192016_508fnl.pdf",
    "Minnesota - Volume to Weight Conversions (2021)": "https://www.pca.state.mn.us/sites/default/files/w-sw2-08.pdf",
}


def main() -> None:
    documents = []
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        for title, url in SOURCES.items():
            response = client.get(url)
            response.raise_for_status()
            for page_number, page in enumerate(PdfReader(BytesIO(response.content)).pages, start=1):
                content = page.extract_text() or ""
                if content.strip():
                    documents.append(Document(page_content=content, metadata={
                        "source_id": f"{url}#page={page_number}", "title": title,
                        "url": url, "page": page_number,
                    }))
    count = FederatedRag(get_settings()).ingest_documents("weight", documents)
    print(f"{count} trechos indexados no corpus weight.")


if __name__ == "__main__":
    main()
