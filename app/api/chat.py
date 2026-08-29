from time import perf_counter
from uuid import uuid4
import anyio

from fastapi import APIRouter, Depends, HTTPException, status

# Nossos modelos Pydantic (movidos para models.py)
from app.db.models import (
    ChatRequest,
    ChatResponse,
    CorporateAnswer,
    RouteName,
    SourceCitation,
    SpecialistResult,
    JudgeVerdict,
)

# Nossas lógicas isoladas
from app.core.guardrails import guardrail_entrada, guardrail_saida
from app.db.storage import SessionRepository
from app.core.observability import Observability

# Função fictícia para ilustrar a injeção do Grafo (você pode colocar isso no storage.py ou num dependencies.py)
from app.core.dependencies import get_sessions, get_telemetry, get_graph

router = APIRouter()

@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    sessions: SessionRepository = Depends(get_sessions),
    telemetry: Observability = Depends(get_telemetry),
    graph = Depends(get_graph)
) -> ChatResponse:
    """
    Processa a requisição do usuário passando pela arquitetura Multiagente.
    Inclui guardrails, auditoria e execução isolada de thread para não bloquear o servidor.
    """
    started = perf_counter()
    request_id = uuid4()
    
    try:
        # 1. Validação de Sessão e Segurança
        sessions.ensure_session_owner(payload.session_id, payload.tenant_id, payload.user_id)
        
        outer_guardrail = guardrail_entrada(payload.message)
        
        # 2. Bloqueio imediato se ferir as diretrizes
        if outer_guardrail.blocked:
            sessions.audit_security_event(payload.session_id, outer_guardrail.reason or "input_blocked")
            answer = CorporateAnswer(
                title="Solicitação bloqueada",
                answer=guardrail_saida(outer_guardrail.reason or "Solicitação bloqueada pelas diretrizes de segurança."),
                recommended_actions=["Reformule a solicitação para o escopo de resíduos, ESG ou operações."]
            )
            telemetry.record_request("blocked", started, "blocked")
            return ChatResponse(
                request_id=request_id, 
                session_id=payload.session_id, 
                route=RouteName.BLOCKED, 
                response=answer
            )

        # 3. Histórico Seguro (Salvando apenas a mensagem já higienizada de PII)
        sessions.append_message(payload.session_id, "user", outer_guardrail.sanitized_text, str(request_id))
        
        # 4. Estado inicial do Grafo (LangGraph)
        graph_input = {
            "messages": [{"role": "user", "content": outer_guardrail.sanitized_text}],
            "request_id": str(request_id),
            "user_id": payload.user_id,
            "tenant_id": payload.tenant_id,
            "session_id": payload.session_id,
            "input_text": outer_guardrail.sanitized_text,
        }
        
        config = {"configurable": {"thread_id": payload.session_id}}
        
        # 5. Execução do Multiagente (O professor alerta: NÃO bloquear o event loop aqui!)
        result = await anyio.to_thread.run_sync(lambda: graph.invoke(graph_input, config=config))
        
        # 6. Parse Estruturado (Type Hints e Pydantic em ação)
        answer = CorporateAnswer.model_validate(result["corporate_answer"])
        route = RouteName(result["route"])
        citations = [SourceCitation.model_validate(item) for item in result.get("evidence", [])]
        
        specialist = None
        if result.get("specialist"):
            specialist = SpecialistResult.model_validate(result["specialist"])
            
        judge = None
        if result.get("judge"):
            judge = JudgeVerdict.model_validate(result["judge"])
        
        # 7. Finalização, persistência e resposta
        sessions.append_message(payload.session_id, "assistant", answer.answer, str(request_id))
        if judge is not None:
            telemetry.record_judge(judge.approved, human_intervention=not judge.approved)
        telemetry.record_request(route.value, started, "success", resolved=not judge or judge.approved)
        
        return ChatResponse(
            request_id=request_id,
            session_id=payload.session_id,
            route=route,
            response=answer,
            citations=citations,
            proposed_occurrence=specialist.proposed_occurrence if specialist else None,
            judge=judge,
        )
        
    except PermissionError as exc:
        telemetry.record_request("authorization", started, "forbidden")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sessão não autorizada.") from exc
        
    except Exception as exc:
        import traceback
        traceback.print_exc()
        telemetry.record_request("unknown", started, "error")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Não foi possível concluir a análise operacional.") from exc
