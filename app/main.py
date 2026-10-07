from contextlib import asynccontextmanager
import logging
import uuid
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
from app.core.request_context import RequestIdFilter, request_id_context


_handler = logging.StreamHandler()
logging.basicConfig(level=logging.INFO, handlers=[_handler])
_formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s")
for _configured_handler in logging.getLogger().handlers:
    _configured_handler.setFormatter(_formatter)
    _configured_handler.addFilter(RequestIdFilter())


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
    app.state.rag = rag
    app.state.team = team
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


@app.middleware("http")
async def attach_request_id(request, call_next):
    request_id = str(uuid.uuid4())
    token = request_id_context.set(request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        request_id_context.reset(token)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["authorization", "content-type", "x-admin-key"],
)


@app.get("/health/live", tags=["System"])
def liveness() -> dict:
    return {"status": "alive"}


@app.get("/health", tags=["System"])
@app.get("/health/ready", tags=["System"])
def health(response: Response) -> dict:
    try:
        postgres_ok = db_postgres.healthcheck()
        mongo_ok = db_mongo.healthcheck()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dependência de banco de dados indisponível.",
        ) from exc

    if not postgres_ok or not mongo_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
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
