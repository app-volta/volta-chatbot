from scripts import ingest_weight_references as ingestion


def test_ingestion_preserves_official_source_and_page(monkeypatch):
    captured = {}

    class Response:
        content = b"pdf"

        def raise_for_status(self):
            pass

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url):
            assert url in ingestion.SOURCES.values()
            return Response()

    class Page:
        def extract_text(self):
            return "Material: cardboard; unit: pounds per cubic yard."

    class Reader:
        def __init__(self, source):
            self.pages = [Page()]

    class Rag:
        def __init__(self, settings):
            pass

        def ingest_documents(self, corpus, documents):
            captured.update(corpus=corpus, documents=documents)
            return len(documents)

    monkeypatch.setattr(ingestion.httpx, "Client", Client)
    monkeypatch.setattr(ingestion, "PdfReader", Reader)
    monkeypatch.setattr(ingestion, "FederatedRag", Rag)
    monkeypatch.setattr(ingestion, "get_settings", lambda: None)
    ingestion.main()
    assert captured["corpus"] == "weight"
    assert {doc.metadata["url"] for doc in captured["documents"]} == set(ingestion.SOURCES.values())
    assert all(doc.metadata["page"] == 1 for doc in captured["documents"])
