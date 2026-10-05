from fastapi import APIRouter, Depends, HTTPException, status

# Modelos do Pydantic
from langchain_core.documents import Document

from app.ai.agents import AgentTeam
from app.ai.multi_rag import FederatedRag
from app.core.dependencies import get_agent_team, get_rag, get_sessions
from app.core.auth import RequestIdentity, get_current_identity
from app.core.guardrails import guardrail_entrada
from app.db.models import SessionCloseResponse, SessionResponse

# Injeção de Dependência
from app.db.storage import SessionRepository
router = APIRouter()

@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    identity: RequestIdentity = Depends(get_current_identity),
    sessions: SessionRepository = Depends(get_sessions)
) -> SessionResponse:
    """Cria uma nova sessão isolada por tenant (empresa) e usuário."""
    document = sessions.create_session(identity.tenant_id, identity.user_id)
    return SessionResponse(**document)


@router.get("/{session_id}/history")
def history(
    session_id: str, 
    identity: RequestIdentity = Depends(get_current_identity),
    sessions: SessionRepository = Depends(get_sessions)
) -> dict:
    """Busca o histórico recente de mensagens do MongoDB."""
    try:
        sessions.ensure_session_owner(session_id, identity.tenant_id, identity.user_id)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Sessão não autorizada."
        ) from exc
        
    return {"session_id": session_id, "messages": sessions.recent_history(session_id)}


@router.post("/{session_id}/close", response_model=SessionCloseResponse)
def close(
    session_id: str,
    identity: RequestIdentity = Depends(get_current_identity),
    sessions: SessionRepository = Depends(get_sessions),
    rag: FederatedRag = Depends(get_rag),
    team: AgentTeam = Depends(get_agent_team),
) -> SessionCloseResponse:
    """Resume e indexa a memória semântica antes de fechar a sessão."""
    try:
        sessions.ensure_session_owner(session_id, identity.tenant_id, identity.user_id)
        messages = sessions.session_history(session_id)
        summary_indexed = False
        if messages:
            summary = guardrail_entrada(team.summarize_session(messages))
            if summary.blocked or not summary.sanitized_text.strip():
                raise ValueError("Não foi possível gerar um resumo seguro para a sessão.")
            summary_indexed = bool(
                rag.ingest_documents(
                    "history",
                    [
                        Document(
                            page_content=summary.sanitized_text,
                            metadata={
                                "source_id": session_id,
                                "session_id": session_id,
                                "tenant_id": identity.tenant_id,
                                "title": "Resumo da sessão",
                                "location": "sessão encerrada",
                            },
                        )
                    ],
                )
            )
        closed_at = sessions.close_session(session_id, identity.tenant_id, identity.user_id)
        return SessionCloseResponse(
            session_id=session_id,
            closed_at=closed_at,
            summary_indexed=summary_indexed,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sessão não autorizada.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Não foi possível encerrar a sessão.") from exc
