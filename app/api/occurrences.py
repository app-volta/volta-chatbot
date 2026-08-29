import base64
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from app.ai.predictive import prever_volume_futuro
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from app.db.storage import db_postgres

# Nossos modelos Pydantic centralizados
from app.db.models import (
    OccurrenceDraftCreate,
    OccurrenceDraftResponse,
    ApprovalRequest,
    ApprovalResponse,
    AnaliseResiduoIA  # <-- Nosso contrato da IA!
)

# Repositorio, Injecao de Dependencia e Config
from app.db.storage import PostgresRepository
from app.core.dependencies import get_postgres
from app.core.dependencies import get_telemetry
from app.core.config import get_settings
from app.core.observability import Observability

router = APIRouter()
MAX_IMAGE_BYTES = 10 * 1024 * 1024

@router.post("/drafts", response_model=OccurrenceDraftResponse, status_code=status.HTTP_201_CREATED)
def create_occurrence_draft(
    payload: OccurrenceDraftCreate,
    repository: PostgresRepository = Depends(get_postgres)
) -> OccurrenceDraftResponse:
    """
    Recebe a revisao final do usuario (Front-end) e grava o rascunho 
    nas tabelas 'incident' e 'ai_report'.
    """
    # Converte o Pydantic ai_data em um dicionario para o repositorio
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
    Retorna os ultimos rascunhos cadastrados no banco para o Front-end renderizar a tela de aprovacao.
    """
    drafts = repository.get_all_drafts()
    return {"total": len(drafts), "data": drafts}


@router.post("/drafts/{draft_id}/approve", response_model=ApprovalResponse)
def approve_occurrence_draft(
    draft_id: int, 
    payload: ApprovalRequest,
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
        occurrence_id = repository.approve_occurrence_draft(draft_id)
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
    area_id: int,
    tenant_id: str = Query(..., min_length=1, max_length=128),
    capacidade_maxima: float = Query(default=1000.0, gt=0),
    dias_futuros: int = Query(default=7, ge=0, le=365),
    repository: PostgresRepository = Depends(get_postgres)
):
    """
    Busca o historico de lixo da area e preve quando a cacamba vai lotar.
    """
    dados_historicos = repository.get_incident_history_by_area(area_id, tenant_id)
    
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

@router.get("/reports/ai_summary")
def generate_ai_management_summary():
    
    recent_data = db_postgres.get_recent_incidents(limit=5)
    
    if not recent_data:
        return {"resumo": "Sem dados suficientes para analise."}
        
    prompt = f"""
    Aja como um analista de BI e Meio Ambiente.
    Analise os seguintes registros recentes de descarte de residuos industriais:
    {recent_data}
    
    Gere um JSON com as seguintes chaves:
    1. "problema_analisado": Um resumo curto do padrao dos ultimos descartes.
    2. "recomendacoes": Uma lista de 2 acoes preventivas para a equipe.
    """
    
    # Aqui voce conecta com a sua chamada do Gemini ou com os Agentes do LangGraph
    # resposta_ia = sua_funcao_ai(prompt)
    
    return {
        "status": "sucesso",
        "prompt_pronto": prompt,
        "aviso": "Lembre de plugar a chamada real da IA aqui!"
    }
