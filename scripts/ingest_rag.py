"""Indexa documentos locais nos corpora FAISS do VOLTA."""

import argparse
from pathlib import Path

from app.ai.multi_rag import CORPORA, FederatedRag
from app.core.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", choices=CORPORA, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--directory", type=Path, help="Diretório local com PDF, TXT ou Markdown.")
    source.add_argument("--url", help="URL HTTPS de fonte oficial permitida na configuração.")
    parser.add_argument("--title", help="Título usado na citação da fonte externa.")
    args = parser.parse_args()

    rag = FederatedRag(get_settings())
    if args.url:
        if not args.title:
            parser.error("--title é obrigatório quando --url é informado.")
        indexed = rag.ingest_external_url(args.corpus, args.url, args.title)
    else:
        indexed = rag.ingest_directory(args.corpus, args.directory)
    print(f"{indexed} chunks indexados no corpus {args.corpus}.")


if __name__ == "__main__":
    main()
