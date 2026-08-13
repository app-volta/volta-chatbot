from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status

# Nossos modelos Pydantic centralizados
from app.db.models import (
    OccurrenceDraftCreate,
    OccurrenceDraftResponse,
    ApprovalRequest,
    ApprovalResponse,
)

# Repositório e Injeção de Dependência
from app.db.storage import PostgresRepository
from app.core.dependencies import get_postgres  # Puxando do nosso injetor central

router = APIRouter()

@router.post("/drafts", response_model=OccurrenceDraftResponse, status_code=status.HTTP_201_CREATED)
def create_occurrence_draft(
    payload: OccurrenceDraftCreate,
    repository: PostgresRepository = Depends(get_postgres)
) -> OccurrenceDraftResponse:
    """
    Cria um rascunho de ocorrência (Draft).
    Geralmente acionado como consequência da análise do Agente de Triagem (IA).
    O status inicial é sempre restrito para evitar gravação autônoma.
    """
    draft_id = repository.create_occurrence_draft(
        payload.tenant_id, 
        payload.plant_id, 
        payload.created_by, 
        payload.proposal
    )
    return OccurrenceDraftResponse(draft_id=draft_id, status="AGUARDANDO_VALIDACAO")


@router.post("/drafts/{draft_id}/approve", response_model=ApprovalResponse)
def approve_occurrence_draft(
    draft_id: UUID, 
    payload: ApprovalRequest,
    repository: PostgresRepository = Depends(get_postgres)
) -> ApprovalResponse:
    """
    REGRA DE NEGÓCIO CRÍTICA (COMPLIANCE):
    A IA NUNCA escreve a ocorrência final no banco transacional. Um responsável 
    humano (técnico da planta) deve chamar este endpoint para auditar o rascunho 
    gerado pela IA e oficializar o registro no PostgreSQL.
    """
    try:
        occurrence_id = repository.approve_occurrence_draft(draft_id, payload.approved_by)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Rascunho não encontrado."
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, 
            detail="Rascunho já processado."
        ) from exc
        
    return ApprovalResponse(occurrence_id=occurrence_id, status="REGISTRADA")