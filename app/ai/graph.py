"""Fluxo LangGraph do VOLTA, com rotas explícitas e decisão humana fora do LLM."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from langchain_core.messages import AIMessage, AnyMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from app.ai.agents import AgentTeam
from app.core.guardrails import guardrail_entrada, guardrail_saida
from app.ai.multi_rag import FederatedRag
from app.db.models import CorporateAnswer, JudgeVerdict, RouteName, SourceCitation, SpecialistResult


class VoltaState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    request_id: str
    user_id: str
    tenant_id: str
    session_id: str
    input_text: str
    clean_input: str
    route: str
    direct_reply: str
    evidence: list[SourceCitation] # Usando a classe diretamente!
    database_data: list[dict[str, Any]]
    specialist: SpecialistResult   # Usando a classe diretamente!
    judge: JudgeVerdict            # Usando a classe diretamente!
    corporate_answer: CorporateAnswer # Usando a classe diretamente!


def _extract_month_year(text: str) -> tuple[int, int]:
    match = re.search(r"\b(0?[1-9]|1[0-2])[/-](20\d{2})\b", text)
    if match:
        return int(match.group(1)), int(match.group(2))
    months = {
        "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
        "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
        "outubro": 10, "novembro": 11, "dezembro": 12,
    }
    lowered = text.casefold()
    year_match = re.search(r"\b(20\d{2})\b", lowered)
    for name, number in months.items():
        if name in lowered:
            return number, int(year_match.group(1)) if year_match else datetime.now(UTC).year
    now = datetime.now(UTC)
    return now.month, now.year


def _db_citation(title: str, source_id: str, payload: list[dict]) -> SourceCitation:
    return SourceCitation(
        source_id=source_id,
        title=title,
        corpus="history",
        location="consulta parametrizada",
        excerpt=str(payload)[:500],
    )


def build_volta_graph(team: AgentTeam, rag: FederatedRag, checkpointer: Any):
    
    def input_guardrail(state: VoltaState) -> dict:
        result = guardrail_entrada(state["input_text"])
        if result.blocked:
            return {"route": RouteName.BLOCKED.value, "direct_reply": result.reason or "Solicitação bloqueada.", "clean_input": ""}
        return {"clean_input": result.sanitized_text}

    def router(state: VoltaState) -> dict:
        decision = team.route(state["clean_input"])
        return {"route": decision.route.value, "direct_reply": decision.direct_reply or ""}

    def triage(state: VoltaState) -> dict:
        evidence = rag.retrieve_for_route("triage", state["clean_input"])
        result = team.specialist("triage", state["clean_input"], evidence, tenant_id=state["tenant_id"])
        return {"evidence": evidence, "database_data": [], "specialist": result}

    def standards(state: VoltaState) -> dict:
        evidence = rag.retrieve_for_route("standards", state["clean_input"])
        result = team.specialist("standards", state["clean_input"], evidence, tenant_id=state["tenant_id"])
        return {"evidence": evidence, "database_data": [], "specialist": result}

    def data(state: VoltaState) -> dict:
        month, year = _extract_month_year(state["clean_input"])
        try:
            rows = team.postgres.consultar_metricas_esg(month, year, state.get("tenant_id"))
        except Exception:
            rows = [{"availability": "Dados indisponíveis para consulta no momento.", "month": month, "year": year}]
        evidence = [_db_citation("Métricas ESG do PostgreSQL", f"postgres-esg-{year}-{month}", rows)]
        result = team.specialist("data", state["clean_input"], evidence, rows, tenant_id=state["tenant_id"])
        return {"evidence": evidence, "database_data": rows, "specialist": result}

    def performance(state: VoltaState) -> dict:
        try:
            rows = team.postgres.consultar_performance_cooperativas(state.get("tenant_id"))
        except Exception:
            rows = [{"availability": "Indicadores de cooperativas indisponíveis para consulta no momento."}]
        rag_evidence = rag.retrieve_for_route("performance", state["clean_input"])
        evidence = [_db_citation("Indicadores de cooperativas do PostgreSQL", "postgres-cooperatives", rows), *rag_evidence]
        result = team.specialist("performance", state["clean_input"], evidence, rows, tenant_id=state["tenant_id"])
        return {"evidence": evidence, "database_data": rows, "specialist": result}

    def judge(state: VoltaState) -> dict:
        # Como passamos os objetos direto para o estado, não precisamos do model_validate
        verdict = team.judge_result(state["specialist"], state.get("evidence", []), state.get("database_data", []))
        return {"judge": verdict}

    def orchestrator(state: VoltaState) -> dict:
        route = state["route"]
        specialist = state.get("specialist")
        verdict = state.get("judge")
        
        # Se o juiz não aprovou, o orquestrador vai saber que precisa arrumar a resposta baseando-se no 'reason'
        answer = team.format_answer(route, specialist, verdict, state.get("direct_reply"))
        return {"corporate_answer": answer}

    def blocked_response(state: VoltaState) -> dict:
        answer = CorporateAnswer(
            title="Solicitação bloqueada",
            answer=state.get("direct_reply", "A solicitação não pode ser processada pelas diretrizes de segurança do VOLTA."),
            recommended_actions=["Reformule a solicitação dentro do escopo de gestão operacional de resíduos."],
            requires_human_validation=True,
        )
        return {"corporate_answer": answer}

    def output_guardrail(state: VoltaState) -> dict:
        answer = state["corporate_answer"]
        # Só rodamos a limpeza se não for uma resposta bloqueada padrão
        safe_text = guardrail_saida(answer.answer) if state.get("route") != RouteName.BLOCKED.value else answer.answer
        safe_answer = answer.model_copy(update={"answer": safe_text})
        return {"corporate_answer": safe_answer, "messages": [AIMessage(content=safe_answer.answer)]}

    def after_input(state: VoltaState) -> Literal["router", "blocked"]:
        return "blocked" if state.get("route") == RouteName.BLOCKED.value else "router"

    def after_router(state: VoltaState) -> Literal["triage", "standards", "data", "performance", "orchestrator", "blocked"]:
        route = state.get("route")
        if route in {"triage", "standards", "data", "performance"}:
            return route  # type: ignore[return-value]
        if route == "direct":
            return "orchestrator"
        return "blocked"

    # Construção do Grafo
    graph = StateGraph(VoltaState)
    graph.add_node("input_guardrail", input_guardrail)
    graph.add_node("router", router)
    graph.add_node("triage", triage)
    graph.add_node("standards", standards)
    graph.add_node("data", data)
    graph.add_node("performance", performance)
    graph.add_node("judge", judge)
    graph.add_node("orchestrator", orchestrator)
    graph.add_node("blocked", blocked_response)
    graph.add_node("output_guardrail", output_guardrail)
    
    graph.add_edge(START, "input_guardrail")
    graph.add_conditional_edges("input_guardrail", after_input, {"router": "router", "blocked": "blocked"})
    graph.add_conditional_edges(
        "router",
        after_router,
        {"triage": "triage", "standards": "standards", "data": "data", "performance": "performance", "orchestrator": "orchestrator", "blocked": "blocked"},
    )
    for node in ("triage", "standards", "data", "performance"):
        graph.add_edge(node, "judge")
    
    graph.add_edge("judge", "orchestrator")
    graph.add_edge("orchestrator", "output_guardrail")
    graph.add_edge("blocked", "output_guardrail")
    graph.add_edge("output_guardrail", END)
    
    return graph.compile(checkpointer=checkpointer)
