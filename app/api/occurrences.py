import base64
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

# Nossos modelos Pydantic centralizados
from app.db.models import (
    OccurrenceDraftCreate,
    OccurrenceDraftResponse,
    ApprovalRequest,
    ApprovalResponse,
    AnaliseResiduoIA  # <-- Nosso contrato da IA!
)

# Repositório, Injeção de Dependência e Config
from app.db.storage import PostgresRepository
from app.core.dependencies import get_postgres
from app.core.config import get_settings

router = APIRouter()

@router.post("/drafts", response_model=OccurrenceDraftResponse, status_code=status.HTTP_201_CREATED)
def create_occurrence_draft(
    payload: OccurrenceDraftCreate,
    repository: PostgresRepository = Depends(get_postgres)
) -> OccurrenceDraftResponse:
    """
    Recebe a revisão final do usuário (Front-end) e grava o rascunho 
    nas tabelas 'incident' e 'ai_report'.
    """
    # Converte o Pydantic ai_data em um dicionário para o repositório
    ai_dict = payload.ai_data.model_dump()
    
    draft_id = repository.create_occurrence_draft(
        company_id=payload.company_id, 
        area_id=payload.area_id, 
        user_id=payload.user_id, 
        ai_data=ai_dict
    )
    return OccurrenceDraftResponse(draft_id=draft_id, status="AGUARDANDO_VALIDACAO")


@router.get("/drafts")
def list_occurrence_drafts(repository: PostgresRepository = Depends(get_postgres)):
    """
    Retorna os últimos rascunhos cadastrados no banco para o Front-end renderizar a tela de aprovação.
    """
    drafts = repository.get_all_drafts()
    return {"total": len(drafts), "data": drafts}


@router.post("/drafts/{draft_id}/approve", response_model=ApprovalResponse)
def approve_occurrence_draft(
    draft_id: int, 
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
        occurrence_id = repository.approve_occurrence_draft(draft_id)
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


@router.post("/predict", response_model=AnaliseResiduoIA)
async def predict_waste(file: UploadFile = File(...)):
    """
    Recebe a foto do resíduo (via celular do funcionário) e pede para o Gemini 
    analisar o nível de risco, volume e tipo. Retorna um JSON estrito validado.
    """
    # 1. Valida se o que chegou é realmente uma imagem
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Arquivo inválido. Por favor, envie uma imagem.")

    try:
        # 2. Transforma a foto em Base64 para a IA conseguir enxergar
        image_bytes = await file.read()
        image_data = base64.b64encode(image_bytes).decode("utf-8")

        # 3. Puxa as configs do .env e liga a IA
        settings = get_settings()
        llm = ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            temperature=0, 
            api_key=settings.gemini_api_key
        )

        # 4. Força a saída no formato do Pydantic
        structured_llm = llm.with_structured_output(AnaliseResiduoIA)

        # 5. Monta o prompt + foto
        mensagem = HumanMessage(
            content=[
                {
                    "type": "text", 
                    "text": "Você é um auditor ambiental (ESG) linha dura. Analise este resíduo industrial. Identifique o tipo, nível de contaminação aparente, dê uma estimativa visual de volume (se possível) e descreva os EPIs necessários e laudo."
                },
                {
                    "type": "image_url", 
                    "image_url": f"data:{file.content_type};base64,{image_data}"
                }
            ]
        )

        # 6. Manda bala e devolve pronto
        resultado = structured_llm.invoke([mensagem])
        return resultado

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao processar imagem na IA: {str(e)}")