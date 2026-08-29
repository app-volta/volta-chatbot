from contextlib import asynccontextmanager
from fastapi import FastAPI, status, HTTPException
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.mongodb import MongoDBSaver

from app.api import chat, occurrences
from app.core.config import get_settings
from app.core.observability import Observability
from app.ai.multi_rag import FederatedRag
from app.ai.agents import AgentTeam
from app.ai.graph import build_volta_graph
from app.db.storage import db_postgres, db_mongo
from app.api import sessions, observability


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # 1. Abertura das conexões de banco de dados
    db_postgres.open(settings.postgres_url)
    db_mongo.open(settings.mongodb_url)
    db_mongo.ensure_indexes()

    # 2. Módulos de telemetria, RAG e equipe de agentes
    telemetry = Observability(settings)
    rag = FederatedRag(settings)
    team = AgentTeam(settings, rag, db_postgres, telemetry)

    # 3. Checkpointer e Grafo do LangGraph
    checkpointer = MongoDBSaver(db_mongo.client)
    graph = build_volta_graph(team, rag, checkpointer)

    # 4. Registro no state para injeção de dependência nas rotas
    app.state.telemetry = telemetry
    app.state.graph = graph

    yield

    # 5. Encerramento seguro das pools de conexão
    db_postgres.close()
    db_mongo.close()


app = FastAPI(
    title="VOLTA API",
    version="1.0.0",
    description="SaaS B2B para gestão operacional e rastreabilidade de resíduos (ODS 12)",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["content-type", "x-admin-key"],
)


@app.get("/health", tags=["System"])
def health() -> dict:
    try:
        postgres_ok = db_postgres.healthcheck()
        mongo_ok = db_mongo.healthcheck()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dependência de banco de dados indisponível.",
        ) from exc

    return {
        "status": "ok" if postgres_ok and mongo_ok else "degraded",
        "postgres": postgres_ok,
        "mongodb": mongo_ok,
    }


# Rotas da API
app.include_router(chat.router, prefix="/v1/chat", tags=["Chat & IA"])
app.include_router(occurrences.router, prefix="/v1/occurrences", tags=["Ocorrências"])
app.include_router(sessions.router, prefix="/v1/sessions", tags=["Sessões"])
app.include_router(observability.router, prefix="/v1/observability", tags=["Observabilidade"])


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    """Endpoint de scraping Prometheus sem conteúdo de requisições."""
    payload, content_type = Observability.prometheus_payload()
    return Response(content=payload, headers={"Content-Type": content_type})
