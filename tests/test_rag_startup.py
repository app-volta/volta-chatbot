import logging

from app.ai.multi_rag import FederatedRag


def test_empty_local_rag_indexes_are_reported(caplog, tmp_path):
    rag = FederatedRag.__new__(FederatedRag)
    rag._qdrant = None
    rag.base_path = tmp_path

    with caplog.at_level(logging.WARNING, logger="app.ai.multi_rag"):
        rag.log_knowledge_base_status()

    assert "operational" in caplog.text
    assert "regulatory" in caplog.text
    assert "cooperatives" in caplog.text
