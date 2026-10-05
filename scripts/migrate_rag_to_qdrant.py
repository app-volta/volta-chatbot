"""Copia um corpus FAISS existente para Qdrant, preservando os arquivos locais."""

import argparse

from app.ai.multi_rag import CORPORA, FederatedRag
from app.core.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", choices=CORPORA, required=True)
    args = parser.parse_args()
    rag = FederatedRag(get_settings())
    migrated = rag.migrate_faiss_to_qdrant(args.corpus)
    print(f"{migrated} trechos copiados para Qdrant no corpus {args.corpus}.")


if __name__ == "__main__":
    main()
