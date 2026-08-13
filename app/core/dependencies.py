from fastapi import Request
from app.core.config import get_settings
from app.core.observability import Observability
from app.ai.graph import build_volta_graph

# Importando as instâncias e tipagens do nosso novo repositório centralizado
from app.db.storage import db_postgres, db_mongo, PostgresRepository, SessionRepository

def get_postgres() -> PostgresRepository:
    """Injeta a conexão transacional do banco de dados (Ocorrências/Métricas)."""
    # Retorna diretamente a instância global do storage.py
    return db_postgres 

def get_sessions() -> SessionRepository:
    """Injeta o repositório NoSQL do histórico de mensagens."""
    # Retorna diretamente a instância global do storage.py
    return db_mongo

def get_telemetry(request: Request) -> Observability:
    """Injeta o módulo de SRE e métricas."""
    return request.app.state.telemetry

def get_graph(request: Request):
    """Injeta o ecossistema multiagente (LangGraph)."""
    return request.app.state.graph