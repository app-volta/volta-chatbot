from __future__ import annotations

import json
from typing import Any, TypeVar

from langgraph.prebuilt import create_react_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from pydantic import BaseModel

from app.core.config import Settings
from app.ai.multi_rag import FederatedRag, serialize_citations
from app.core.observability import Observability
from app.db.storage import PostgresRepository
from app.ai.prompts import (
    DATA_PROMPT,
    JUDGE_PROMPT,
    ORCHESTRATOR_PROMPT,
    PERFORMANCE_PROMPT,
    ROUTER_PROMPT,
    STANDARDS_PROMPT,
    TRIAGE_PROMPT,
    temporal_context,
)
from app.db.models import CorporateAnswer, JudgeVerdict, RouteDecision, SpecialistResult

SchemaT = TypeVar("SchemaT", bound=BaseModel)

class AgentTeam:
    def __init__(self, settings: Settings, rag: FederatedRag, postgres: PostgresRepository, telemetry: Observability) -> None:
        self.settings = settings
        self.rag = rag
        self.postgres = postgres
        self.telemetry = telemetry
        self.router_model, self.router_model_name = self._router_model()
        self.specialist_model, self.specialist_model_name = self._specialist_model()
        self._create_agents()

    def _router_model(self):
        if self.settings.groq_api_key:
            return (
                ChatGroq(
                    model=self.settings.groq_router_model,
                    temperature=0,
                    api_key=self.settings.groq_api_key.get_secret_value(),
                    timeout=30,
                    max_retries=2,
                ),
                f"groq:{self.settings.groq_router_model}",
            )
        if self.settings.gemini_api_key:
            return (
                ChatGoogleGenerativeAI(
                    model=self.settings.gemini_model,
                    temperature=0,
                    google_api_key=self.settings.gemini_api_key.get_secret_value(),
                    timeout=30,
                    max_retries=2,
                ),
                f"gemini:{self.settings.gemini_model}",
            )
        raise RuntimeError("Defina GEMINI_API_KEY ou GROQ_API_KEY.")

    def _specialist_model(self):
        if self.settings.gemini_api_key:
            primary = ChatGoogleGenerativeAI(
                model=self.settings.gemini_model,
                temperature=0.15,
                google_api_key=self.settings.gemini_api_key.get_secret_value(),
                timeout=45,
                max_retries=2,
            )
            if self.settings.groq_api_key:
                fallback = ChatGroq(
                    model=self.settings.groq_router_model,
                    temperature=0,
                    api_key=self.settings.groq_api_key.get_secret_value(),
                    timeout=45,
                    max_retries=2,
                )
                return primary.with_fallbacks([fallback]), f"gemini:{self.settings.gemini_model}"
            return primary, f"gemini:{self.settings.gemini_model}"
        return self._router_model()

    def _create_agents(self) -> None:
        @tool
        def consultar_rag_operacional(query: str) -> str:
            """Consulta manuais industriais e FISPQs indexados, com fonte e trecho."""
            return serialize_citations(self.rag.retrieve("operational", query))

        @tool
        def consultar_rag_regulatorio(query: str) -> str:
            """Consulta fontes regulatórias e ODS 12 indexados, com fonte e trecho."""
            return serialize_citations(self.rag.retrieve("regulatory", query))

        @tool
        def consultar_rag_cooperativas(query: str) -> str:
            """Consulta contratos e regras operacionais de cooperativas indexados."""
            return serialize_citations(self.rag.retrieve("cooperatives", query))

        @tool
        def consultar_metricas_esg(month: int, year: int, tenant_id: str) -> str:
            """Consulta agregados ESG de leitura no PostgreSQL. Mes deve estar entre 1 e 12."""
            if not 1 <= month <= 12:
                return json.dumps({"erro": "Mês inválido"})
            if not tenant_id.strip():
                return json.dumps({"erro": "tenant_id obrigatório"})
            return json.dumps(self.postgres.consultar_metricas_esg(month, year, tenant_id), default=str, ensure_ascii=False)

        @tool
        def consultar_performance_cooperativas(tenant_id: str) -> str:
            """Consulta indicadores de SLA e resposta de cooperativas no PostgreSQL."""
            if not tenant_id.strip():
                return json.dumps({"erro": "tenant_id obrigatório"})
            return json.dumps(self.postgres.consultar_performance_cooperativas(tenant_id), default=str, ensure_ascii=False)

        # 1. Agentes Controladores -> Usam Structured Output puro
        prompt_router = ChatPromptTemplate.from_messages([("system", ROUTER_PROMPT.format(now=temporal_context())), ("user", "{input}")])
        self.router = prompt_router | self.router_model.with_structured_output(RouteDecision)

        prompt_judge = ChatPromptTemplate.from_messages([("system", JUDGE_PROMPT), ("user", "{input}")])
        self.judge = prompt_judge | self.specialist_model.with_structured_output(JudgeVerdict)

        prompt_orchestrator = ChatPromptTemplate.from_messages([("system", ORCHESTRATOR_PROMPT), ("user", "{input}")])
        self.orchestrator = prompt_orchestrator | self.router_model.with_structured_output(CorporateAnswer)

        # 2. Especialistas com Tools -> Construídos nativamente com o LangGraph
        def _build_specialist(prompt_text, tools):
            return create_react_agent(
                self.specialist_model, 
                tools=tools, 
                prompt=prompt_text
            )

        self.triage = _build_specialist(TRIAGE_PROMPT, [consultar_rag_operacional])
        self.standards = _build_specialist(STANDARDS_PROMPT, [consultar_rag_operacional, consultar_rag_regulatorio])
        self.data = _build_specialist(DATA_PROMPT, [consultar_metricas_esg])
        self.performance = _build_specialist(PERFORMANCE_PROMPT, [consultar_rag_cooperativas, consultar_performance_cooperativas])

    def _invoke_controller(self, name: str, runnable: Any, model: str, payload: str) -> Any:
        started = self.telemetry.timer()
        try:
            parsed = runnable.invoke({"input": payload})
            self.telemetry.record_agent(name, model, started, payload, parsed.model_dump_json())
            return parsed
        except Exception as exc:
            self.telemetry.record_agent(name, model, started, payload, str(exc), failed=True)
            raise RuntimeError(f"Falha controlada no controlador {name}.") from exc

    def _invoke_specialist(self, name: str, executor: Any, model: str, payload: str) -> SpecialistResult:
        started = self.telemetry.timer()
        try:
            result = executor.invoke({"messages": [("user", payload)]})
            final_message = result["messages"][-1]
            
            if hasattr(final_message, "parsed") and final_message.parsed:
                parsed = final_message.parsed
            else:
                structured_parser = self.specialist_model.with_structured_output(SpecialistResult)
                parsed = structured_parser.invoke(f"Converta essa resposta para JSON: {final_message.content}")
            
            self.telemetry.record_agent(name, model, started, payload, parsed.model_dump_json())
            return parsed
        except Exception as exc:
            print(f"\n[ERRO FATAL NO AGENTE {name}]")
            print(exc) 
            print("[/ERRO FATAL]\n")

            self.telemetry.record_agent(name, model, started, payload, str(exc), failed=True)
            raise RuntimeError(f"Falha controlada no especialista {name}.") from exc

    def route(self, message: str) -> RouteDecision:
        return self._invoke_controller("router", self.router, self.router_model_name, f"Data UTC: {temporal_context()}\n\nMensagem: {message}")

    def specialist(self, route: str, message: str, evidence: list, data: list[dict] | None = None, *, tenant_id: str) -> SpecialistResult:
        selected = {"triage": self.triage, "standards": self.standards, "data": self.data, "performance": self.performance}[route]
        context = {"message": message, "tenant_id": tenant_id, "evidence": [item.model_dump(mode="json") for item in evidence], "database_data": data or []}
        return self._invoke_specialist(route, selected, self.specialist_model_name, json.dumps(context, ensure_ascii=False))

    def judge_result(self, specialist: SpecialistResult, evidence: list, data: list[dict] | None = None) -> JudgeVerdict:
        context = {
            "specialist_result": specialist.model_dump(mode="json"),
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "database_data": data or [],
        }
        return self._invoke_controller("judge", self.judge, self.specialist_model_name, json.dumps(context, ensure_ascii=False))

    def format_answer(self, route: str, specialist: SpecialistResult | None, judge: JudgeVerdict | None, direct_reply: str | None = None) -> CorporateAnswer:
        context = {"route": route, "specialist": specialist.model_dump(mode="json") if specialist else None, "judge": judge.model_dump(mode="json") if judge else None, "direct_reply": direct_reply}
        return self._invoke_controller("orchestrator", self.orchestrator, self.router_model_name, json.dumps(context, ensure_ascii=False))
