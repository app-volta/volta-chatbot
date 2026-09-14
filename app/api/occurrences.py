import base64
import json
from uuid import UUID
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from app.ai.predictive import prever_volume_futuro
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
# Nossos modelos Pydantic centralizados
from app.db.models import (
    OccurrenceDraftCreate,
    OccurrenceDraftResponse,
    ApprovalResponse,
    AnaliseResiduoIA,
    AIManagementSummary,
)

# Repositorio, Injecao de Dependencia e Config
from app.db.storage import PostgresRepository
from app.core.dependencies import get_postgres
from app.core.dependencies import get_telemetry
from app.core.config import get_settings
from app.core.observability import Observability
from app.core.auth import RequestIdentity, get_current_identity
from app.core.guardrails import guardrail_entrada

router = APIRouter()
MAX_IMAGE_BYTES = 10 * 1024 * 1024

@router.post("/drafts", response_model=OccurrenceDraftResponse, status_code=status.HTTP_201_CREATED)
def create_occurrence_draft(
    payload: OccurrenceDraftCreate,
    identity: RequestIdentity = Depends(get_current_identity),
    repository: PostgresRepository = Depends(get_postgres)
) -> OccurrenceDraftResponse:
    """
    Recebe a revisao final do usuario (Front-end) e grava o rascunho 
    nas tabelas 'incident' e 'ai_report'.
    """
    # Converte o Pydantic ai_data em um dicionario para o repositorio
    ai_dict = payload.ai_data.model_dump()
    try:
        company_id = UUID(identity.tenant_id)
        user_id = UUID(identity.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Identidade autenticada inválida para criar ocorrência.") from exc
    
    try:
        draft_id = repository.create_occurrence_draft(
            company_id=company_id,
            area_id=payload.area_id,
            user_id=user_id,
            employee_description=payload.employee_description,
            priority=payload.priority,
            ai_data=ai_dict,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Área não encontrada para esta empresa.") from exc
    return OccurrenceDraftResponse(draft_id=draft_id, status="AGUARDANDO_VALIDACAO")


@router.get("/drafts")
def list_occurrence_drafts(
    identity: RequestIdentity = Depends(get_current_identity),
    repository: PostgresRepository = Depends(get_postgres),
):
    """
    Retorna os ultimos rascunhos cadastrados no banco para o Front-end renderizar a tela de aprovacao.
    """
    drafts = repository.get_all_drafts(identity.tenant_id)
    return {"total": len(drafts), "data": drafts}


@router.post("/drafts/{draft_id}/approve", response_model=ApprovalResponse)
def approve_occurrence_draft(
    draft_id: UUID,
    identity: RequestIdentity = Depends(get_current_identity),
    repository: PostgresRepository = Depends(get_postgres),
    telemetry: Observability = Depends(get_telemetry),
) -> ApprovalResponse:
    """
    REGRA DE NEGOCIO CRITICA (COMPLIANCE):
    A IA NUNCA escreve a ocorrencia final no banco transacional. Um responsavel 
    humano (tecnico da planta) deve chamar este endpoint para auditar o rascunho 
    gerado pela IA e oficializar o registro no PostgreSQL.
    """
    try:
        occurrence_id = repository.approve_occurrence_draft(draft_id, identity.tenant_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Rascunho nao encontrado."
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, 
            detail="Rascunho ja processado."
        ) from exc

    telemetry.record_human_intervention("occurrence_approval")
    return ApprovalResponse(occurrence_id=occurrence_id, status="REGISTRADA")


@router.post("/predict", response_model=AnaliseResiduoIA)
async def predict_waste(
    file: UploadFile = File(...),
    _identity: RequestIdentity = Depends(get_current_identity),
    telemetry: Observability = Depends(get_telemetry),
):
    """
    Recebe a foto do residuo (via celular do funcionario) e pede para o Gemini 
    analisar o nivel de risco, volume e tipo. Retorna um JSON estrito validado.
    """
    # 1. Valida se o que chegou e realmente uma imagem
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Arquivo invalido. Por favor, envie uma imagem.")

    started = telemetry.timer()
    model_name = "gemini:visual-triage"
    try:
        # 2. Transforma a foto em Base64 para a IA conseguir enxergar
        image_bytes = await file.read(MAX_IMAGE_BYTES + 1)
        if not image_bytes:
            raise HTTPException(status_code=400, detail="A imagem enviada esta vazia.")
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="A imagem excede o limite de 10 MB.")
        image_data = base64.b64encode(image_bytes).decode("utf-8")

        # 3. Puxa as configs do .env e liga a IA
        settings = get_settings()
        if settings.gemini_api_key is None:
            raise HTTPException(status_code=503, detail="Analise visual indisponivel: provedor de IA nao configurado.")
        model_name = f"gemini:{settings.gemini_model}"
        llm = ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            temperature=0, 
            api_key=settings.gemini_api_key.get_secret_value()
        )

        # 4. Forca a saida no formato do Pydantic
        structured_llm = llm.with_structured_output(AnaliseResiduoIA)

        # 5. Monta o prompt + foto
        mensagem = HumanMessage(
            content=[
                {
                    "type": "text", 
                    "text": "Voce e um auditor ambiental (ESG) linha dura. Analise este residuo industrial. Identifique o tipo, nivel de contaminacao aparente, de uma estimativa visual de volume (se possivel) e descreva os EPIs necessarios e laudo."
                },
                {
                    "type": "image_url", 
                    "image_url": f"data:{content_type};base64,{image_data}"
                }
            ]
        )

        # 6. Manda bala e devolve pronto
        resultado = structured_llm.invoke([mensagem])
        telemetry.record_agent(
            "visual_triage",
            model_name,
            started,
            "visual_triage_request",
            resultado.model_dump_json(),
        )
        return resultado

    except HTTPException:
        raise
    except Exception as e:
        telemetry.record_agent(
            "visual_triage",
            model_name,
            started,
            "visual_triage_request",
            str(e),
            failed=True,
        )
        raise HTTPException(status_code=502, detail="Nao foi possivel concluir a analise visual no momento.") from e


@router.get("/areas/{area_id}/predict_capacity")
def predict_area_capacity(
    area_id: UUID,
    identity: RequestIdentity = Depends(get_current_identity),
    capacidade_maxima: float = Query(default=1000.0, gt=0),
    dias_futuros: int = Query(default=7, ge=0, le=365),
    repository: PostgresRepository = Depends(get_postgres)
):
    """
    Busca o historico de lixo da area e preve quando a cacamba vai lotar.
    """
    dados_historicos = repository.get_incident_history_by_area(area_id, identity.tenant_id)
    
    if not dados_historicos or len(dados_historicos) < 2:
        raise HTTPException(
            status_code=400, 
            detail="Dados insuficientes para prever o futuro desta cacamba."
        )
        
    previsao = prever_volume_futuro(
        dados_historicos,
        dias_futuros=dias_futuros,
        capacidade_maxima=capacidade_maxima,
    )
    
    return previsao

@router.get("/reports/ai_summary", response_model=AIManagementSummary)
def generate_ai_management_summary(
    identity: RequestIdentity = Depends(get_current_identity),
    repository: PostgresRepository = Depends(get_postgres),
    telemetry: Observability = Depends(get_telemetry),
):

    recent_data = repository.get_recent_incidents(limit=5, tenant_id=identity.tenant_id)

    if not recent_data:
        return AIManagementSummary(
            problema_analisado="Sem dados suficientes para análise.",
            recomendacoes=[],
        )

    safe_data = []
    for row in recent_data:
        safe_row = dict(row)
        description = str(safe_row.get("employee_description", ""))
        safe_row["employee_description"] = guardrail_entrada(description).sanitized_text
        safe_data.append(safe_row)

    prompt = (
        "Aja como um analista de BI e meio ambiente. Analise os registros recentes "
        "de descarte de resíduos industriais abaixo. Retorne apenas o schema solicitado, "
        "sem inventar métricas ausentes. Gere um resumo curto do padrão observado e "
        "recomendações preventivas acionáveis.\n\n"
        f"Registros: {json.dumps(safe_data, ensure_ascii=False, default=str)}"
    )
    settings = get_settings()
    if settings.gemini_api_key is None:
        raise HTTPException(status_code=503, detail="Relatório de IA indisponível: provedor não configurado.")

    started = telemetry.timer()
    model_name = f"gemini:{settings.gemini_model}"
    try:
        llm = ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            temperature=0,
            api_key=settings.gemini_api_key.get_secret_value(),
        )
        structured_llm = llm.with_structured_output(AIManagementSummary)
        result = structured_llm.invoke([HumanMessage(content=prompt)])
        telemetry.record_agent(
            "ai_management_summary",
            model_name,
            started,
            "ai_management_summary_request",
            result.model_dump_json(),
        )
        return result
    except Exception as exc:
        telemetry.record_agent(
            "ai_management_summary",
            model_name,
            started,
            "ai_management_summary_request",
            str(exc),
            failed=True,
        )
        raise HTTPException(status_code=502, detail="Não foi possível gerar o relatório de IA.") from exc
