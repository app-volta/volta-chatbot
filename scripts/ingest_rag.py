"""Indexa documentos locais nos corpora FAISS do VOLTA."""

import argparse
from pathlib import Path

from app.ai.multi_rag import CORPORA, FederatedRag
from app.core.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", choices=CORPORA, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()

    indexed = FederatedRag(get_settings()).ingest_directory(args.corpus, args.directory)
    print(f"{indexed} chunks indexados no corpus {args.corpus}.")


if __name__ == "__main__":
    main()
