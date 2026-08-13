from fastapi import APIRouter, Depends, HTTPException, status

# Modelos do Pydantic
from app.db.models import SessionCreateRequest, SessionResponse

# Injeção de Dependência
from app.db.storage import SessionRepository
from app.core.dependencies import get_sessions

router = APIRouter()

@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: SessionCreateRequest,
    sessions: SessionRepository = Depends(get_sessions)
) -> SessionResponse:
    """Cria uma nova sessão isolada por tenant (empresa) e usuário."""
    document = sessions.create_session(payload.tenant_id, payload.user_id)
    return SessionResponse(**document)


@router.get("/{session_id}/history")
def history(
    session_id: str, 
    tenant_id: str, 
    user_id: str,
    sessions: SessionRepository = Depends(get_sessions)
) -> dict:
    """Busca o histórico recente de mensagens do MongoDB."""
    try:
        sessions.ensure_session_owner(session_id, tenant_id, user_id)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Sessão não autorizada."
        ) from exc
        
    return {"session_id": session_id, "messages": sessions.recent_history(session_id)}