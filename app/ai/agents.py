from __future__ import annotations

import asyncio
import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, TypeVar

from langgraph.prebuilt import create_react_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.shared.exceptions import McpError
import httpx
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from pydantic import BaseModel

from app.core.request_context import log_exception_without_details, provider_error_code
from app.core.config import Settings
from app.ai.multi_rag import FederatedRag, serialize_citations
from app.core.observability import Observability
from app.core.model_usage import ModelUsage
from app.db.storage import PostgresRepository
from app.ai.prompts import (
    DATA_PROMPT,
    JUDGE_PROMPT,
    ORCHESTRATOR_PROMPT,
    PERFORMANCE_PROMPT,
    ROUTER_PROMPT,
    SESSION_SUMMARY_PROMPT,
    STANDARDS_PROMPT,
    TRIAGE_PROMPT,
    temporal_context,
)
from app.db.models import CorporateAnswer, JudgeVerdict, RouteDecision, SessionSummary, SourceCitation, SpecialistResult
from app.ai.mcp_server import mcp as norms_mcp_server

SchemaT = TypeVar("SchemaT", bound=BaseModel)
logger = logging.getLogger(__name__)
SPECIALIST_RECURSION_LIMIT = 12


def _citation_identity(citation: SourceCitation) -> tuple[str, str, str | None, str]:
    return citation.source_id, citation.title, citation.location, citation.excerpt


class _NormsToolError(RuntimeError):
    pass


_NORMS_RECOVERABLE_ERRORS = (httpx.HTTPError, OSError, TimeoutError, McpError, json.JSONDecodeError, _NormsToolError)


def _is_recoverable_norms_error(exc: BaseException) -> bool:
    if isinstance(exc, BaseExceptionGroup):
        return all(_is_recoverable_norms_error(item) for item in exc.exceptions)
    return isinstance(exc, _NORMS_RECOVERABLE_ERRORS)


def _call_norms_mcp(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    started = perf_counter()

    async def call() -> dict[str, Any]:
        async with create_connected_server_and_client_session(norms_mcp_server) as session:
            response = await session.call_tool(tool_name, arguments)
        if response.isError:
            raise _NormsToolError("MCP retornou erro ao consultar o catálogo.")
        text = next((block.text for block in response.content if hasattr(block, "text")), None)
        if text is None:
            raise _NormsToolError("MCP retornou resposta sem conteúdo textual.")
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise _NormsToolError("MCP retornou formato de dados inválido.")
        return payload

    try:
        payload = asyncio.run(call())
    except ExceptionGroup as exc:
        if not _is_recoverable_norms_error(exc):
            raise
        log_exception_without_details(logger, "Norms MCP call failed; continuing with available RAG evidence", exc)
        payload = {"error": "Catálogo externo temporariamente indisponível; use as evidências RAG disponíveis."}
    except _NORMS_RECOVERABLE_ERRORS as exc:
        log_exception_without_details(logger, "Norms MCP call failed; continuing with available RAG evidence", exc)
        payload = {"error": "Catálogo externo temporariamente indisponível; use as evidências RAG disponíveis."}

    citations = _norm_citations(payload)
    logger.info(
        "Norms tool completed tool=%s status=%s duration_ms=%.1f citation_count=%s",
        tool_name,
        "error" if "error" in payload else "success",
        (perf_counter() - started) * 1000,
        len(citations),
    )
    return payload


def _norm_citations(payload: dict[str, Any]) -> list[SourceCitation]:
    # Só o registro detalhado entra em citações; resultados candidatos da busca não são evidência usada.
    record = payload.get("norma")
    if not isinstance(record, dict) or not record.get("ato_normativo") or not record.get("document_key"):
        return []
    excerpt = payload.get("texto_integral") or record.get("ementa", "")
    return [SourceCitation(
        source_id=f"mma-{record['document_key']}",
        title=record["ato_normativo"],
        corpus="regulatory",
        location=record.get("assunto") or record.get("ano"),
        url=record.get("url") or None,
        excerpt=excerpt[:6000],
        retrieved_at=datetime.now(UTC),
    )]


def _evidence_payload(citation: SourceCitation) -> dict[str, Any]:
    if citation.internal_document:
        return {"corpus": citation.corpus, "excerpt": citation.excerpt}
    return citation.model_dump(mode="json")


class AgentTeam:
    def __init__(self, settings: Settings, rag: FederatedRag, postgres: PostgresRepository, telemetry: Observability) -> None:
        self.settings = settings
        self.rag = rag
        self.postgres = postgres
        self.telemetry = telemetry
        self._norm_citation_sink: ContextVar[list[SourceCitation] | None] = ContextVar(
            f"norm_citations_{id(self)}", default=None
        )
        self._rag_citation_sink: ContextVar[list[SourceCitation] | None] = ContextVar(
            f"rag_citations_{id(self)}", default=None
        )
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
            has_fallback = bool(self.settings.groq_api_key)
            primary = ChatGoogleGenerativeAI(
                model=self.settings.gemini_model,
                temperature=0.15,
                google_api_key=self.settings.gemini_api_key.get_secret_value(),
                timeout=20 if has_fallback else 45,
                max_retries=0 if has_fallback else 2,
            )
            self._specialist_primary_model = primary
            if self.settings.groq_api_key:
                fallback = ChatGroq(
                    model=self.settings.groq_router_model,
                    temperature=0,
                    api_key=self.settings.groq_api_key.get_secret_value(),
                    timeout=45,
                    max_retries=2,
                    model_kwargs={"parallel_tool_calls": False},
                )
                self._specialist_fallback_model = fallback
                return primary, f"gemini:{self.settings.gemini_model}"
            self._specialist_fallback_model = None
            return primary, f"gemini:{self.settings.gemini_model}"
        model, model_name = self._router_model()
        self._specialist_primary_model = model
        self._specialist_fallback_model = None
        return model, model_name

    def _structured_specialist(self, schema: type[SchemaT]):
        parser = self._specialist_primary_model.with_structured_output(schema)
        if self._specialist_fallback_model is not None:
            parser = parser.with_fallbacks([
                self._specialist_fallback_model.with_structured_output(schema, method="json_schema")
            ])
        return parser

    def _create_agents(self) -> None:
        def retrieve_rag(corpus: str, query: str) -> list[SourceCitation]:
            started = perf_counter()
            try:
                citations = self.rag.retrieve(corpus, query)
            except Exception:
                logger.info(
                    "RAG tool completed corpus=%s status=error duration_ms=%.1f citation_count=0",
                    corpus,
                    (perf_counter() - started) * 1000,
                )
                raise
            sink = self._rag_citation_sink.get()
            if sink is not None:
                known = {_citation_identity(item) for item in sink}
                for item in citations:
                    identity = _citation_identity(item)
                    if identity not in known:
                        sink.append(item)
                        known.add(identity)
            logger.info(
                "RAG tool completed corpus=%s status=success duration_ms=%.1f citation_count=%s",
                corpus,
                (perf_counter() - started) * 1000,
                len(citations),
            )
            return citations

        def call_norms_mcp(tool_name: str, arguments: dict[str, Any]) -> str:
            payload = _call_norms_mcp(tool_name, arguments)
            sink = self._norm_citation_sink.get()
            if sink is not None:
                known = {_citation_identity(item) for item in sink}
                for citation in _norm_citations(payload):
                    identity = _citation_identity(citation)
                    if identity not in known:
                        sink.append(citation)
                        known.add(identity)
            return json.dumps(payload, ensure_ascii=False)

        @tool
        def consultar_rag_operacional(query: str) -> str:
            """Consulta conteúdo de manuais industriais e FISPQs sem expor metadados internos."""
            return serialize_citations(retrieve_rag("operational", query))

        @tool
        def consultar_rag_regulatorio(query: str) -> str:
            """Consulta fontes regulatórias e ODS 12 indexados, com fonte e trecho."""
            return serialize_citations(retrieve_rag("regulatory", query))

        @tool
        def consultar_rag_cooperativas(query: str) -> str:
            """Consulta contratos e regras operacionais de cooperativas indexados."""
            return serialize_citations(retrieve_rag("cooperatives", query))

        @tool
        def buscar_normas_residuos(termo: str, ano: int | None = None, assunto: str | None = None, limite: int = 5) -> str:
            """Pesquisa legislação ambiental fora do RAG no catálogo oficial do MMA."""
            return call_norms_mcp(
                "buscar_normas_residuos",
                {"termo": termo, "ano": ano, "assunto": assunto, "limite": limite},
            )

        @tool
        def detalhar_norma(document_key: str) -> str:
            """Detalha um resultado do catálogo externo; use o document_key retornado pela busca."""
            return call_norms_mcp("detalhar_norma", {"document_key": document_key})

        # 1. Agentes Controladores -> Usam Structured Output puro
        prompt_router = ChatPromptTemplate.from_messages([("system", ROUTER_PROMPT.format(now=temporal_context())), ("user", "{input}")])
        self.router = prompt_router | self.router_model.with_structured_output(RouteDecision)

        prompt_judge = ChatPromptTemplate.from_messages([("system", JUDGE_PROMPT), ("user", "{input}")])
        self.judge = prompt_judge | self._structured_specialist(JudgeVerdict)

        prompt_orchestrator = ChatPromptTemplate.from_messages([("system", ORCHESTRATOR_PROMPT), ("user", "{input}")])
        self.orchestrator = prompt_orchestrator | self.router_model.with_structured_output(CorporateAnswer)

        # 2. Especialistas com Tools -> Construídos nativamente com o LangGraph
        def _build_specialist(prompt_text, tools, model):
            return create_react_agent(
                model,
                tools=tools,
                prompt=prompt_text,
            )

        # Dados do banco já chegam filtrados pelo tenant autenticado no grafo.
        # Não exponha consultas SQL a tools escolhidas pelo modelo.
        specialist_specs = {
            "triage": (TRIAGE_PROMPT, [consultar_rag_operacional]),
            "standards": (
                STANDARDS_PROMPT,
                [consultar_rag_operacional, consultar_rag_regulatorio, buscar_normas_residuos, detalhar_norma],
            ),
            "data": (DATA_PROMPT, []),
            "performance": (PERFORMANCE_PROMPT, [consultar_rag_cooperativas]),
        }
        for name, (prompt_text, tools) in specialist_specs.items():
            setattr(self, name, _build_specialist(prompt_text, tools, self.specialist_model))
        self._specialist_fallback_agents = {
            name: _build_specialist(prompt_text, tools, self._specialist_fallback_model)
            for name, (prompt_text, tools) in specialist_specs.items()
        } if self._specialist_fallback_model is not None else {}
        self._specialist_no_tools_fallback_agents = {
            name: _build_specialist(
                f"{prompt_text}\n\nCONTINGÊNCIA: ferramentas externas indisponíveis. Use somente as evidências e os dados "
                "já presentes na mensagem. Não afirme que consultou fontes externas; se faltar evidência, informe isso.",
                [],
                self._specialist_fallback_model,
            )
            for name, (prompt_text, _tools) in specialist_specs.items()
        } if self._specialist_fallback_model is not None else {}

    @contextmanager
    def collect_norm_citations(self):
        citations: list[SourceCitation] = []
        token = self._norm_citation_sink.set(citations)
        try:
            yield citations
        finally:
            self._norm_citation_sink.reset(token)

    @contextmanager
    def collect_rag_citations(self):
        citations: list[SourceCitation] = []
        token = self._rag_citation_sink.set(citations)
        try:
            yield citations
        finally:
            self._rag_citation_sink.reset(token)

    def _invoke_controller(self, name: str, runnable: Any, model: str, payload: str) -> Any:
        started = self.telemetry.timer()
        usage = ModelUsage(model)
        try:
            parsed = runnable.invoke({"input": payload}, config={"callbacks": [usage]})
            self.telemetry.record_agent(name, started_at=started, prompt_text=payload, response_text=parsed.model_dump_json(), **usage.measurement())
            return parsed
        except Exception as exc:
            self.telemetry.record_agent(name, started_at=started, prompt_text=payload, response_text="", failed=True, **usage.measurement())
            raise RuntimeError(f"Falha controlada no controlador {name}.") from exc

    def _invoke_specialist(
        self,
        name: str,
        executor: Any,
        model: str,
        payload: str,
        *,
        fallback_executor: Any | None = None,
        fallback_model: str | None = None,
        fallback_no_tools_executor: Any | None = None,
    ) -> SpecialistResult:
        started = self.telemetry.timer()
        usage = ModelUsage(model)
        citation_sink = self._norm_citation_sink.get()
        citation_count = len(citation_sink) if citation_sink is not None else 0
        rag_citation_sink = self._rag_citation_sink.get()
        rag_citation_count = len(rag_citation_sink) if rag_citation_sink is not None else 0

        def invoke(executor: Any, tracker: ModelUsage, *, fallback: bool = False) -> SpecialistResult:
            result = executor.invoke(
                {"messages": [("user", payload)]},
                config={"recursion_limit": SPECIALIST_RECURSION_LIMIT, "callbacks": [tracker]},
            )
            final_message = result["messages"][-1]
            content = final_message.content
            if isinstance(content, list):
                content = "".join(block.get("text", "") for block in content if isinstance(block, dict))
            try:
                return SpecialistResult.model_validate_json(content)
            except (ValueError, TypeError):
                parser = (
                    self._specialist_fallback_model.with_structured_output(
                        SpecialistResult, method="json_schema"
                    )
                    if fallback and self._specialist_fallback_model is not None
                    else self._specialist_primary_model.with_structured_output(SpecialistResult)
                )
                return parser.invoke(
                    "Converta a resposta abaixo para SpecialistResult. Preserve apenas informações fornecidas; "
                    "se campos não se aplicarem, use null. Resposta: " + str(content),
                    config={"callbacks": [tracker]},
                )

        def usage_details(fallback_usage: ModelUsage | None = None) -> dict[str, Any]:
            primary = usage.measurement()
            if fallback_usage is None:
                return primary
            fallback = fallback_usage.measurement()
            return {
                "model": fallback_model or fallback["model"],
                "fallback_used": True,
                "usage": (primary.get("usage") or []) + (fallback.get("usage") or []) or None,
                "usage_complete": primary["usage_complete"] and fallback["usage_complete"],
            }

        try:
            parsed = invoke(executor, usage)
            self.telemetry.record_agent(
                name, started_at=started, prompt_text=payload,
                response_text=parsed.model_dump_json(), **usage_details(),
            )
            return parsed
        except Exception as primary_exc:
            if fallback_executor is None or fallback_model is None:
                log_exception_without_details(logger, f"Specialist {name} failed", primary_exc)
                self.telemetry.record_agent(
                    name, started_at=started, prompt_text=payload, response_text="",
                    failed=True, **usage_details(),
                )
                raise RuntimeError(f"Falha controlada no especialista {name}.") from primary_exc

            log_exception_without_details(
                logger,
                f"Primary specialist {name} failed; restarting with fallback provider",
                primary_exc,
                level=logging.WARNING,
            )
            if citation_sink is not None:
                del citation_sink[citation_count:]
            if rag_citation_sink is not None:
                del rag_citation_sink[rag_citation_count:]
            fallback_usage = ModelUsage(fallback_model)
            try:
                parsed = invoke(fallback_executor, fallback_usage, fallback=True)
            except Exception as fallback_exc:
                if fallback_no_tools_executor is None or provider_error_code(fallback_exc) != "tool_use_failed":
                    log_exception_without_details(logger, f"Fallback specialist {name} failed", fallback_exc)
                    self.telemetry.record_agent(
                        name, started_at=started, prompt_text=payload, response_text="",
                        failed=True, **usage_details(fallback_usage),
                    )
                    raise RuntimeError(f"Falha controlada no especialista {name}.") from fallback_exc

                log_exception_without_details(
                    logger,
                    f"Groq tool call failed for specialist {name}; retrying with supplied evidence only",
                    fallback_exc,
                    level=logging.WARNING,
                )
                if citation_sink is not None:
                    del citation_sink[citation_count:]
                if rag_citation_sink is not None:
                    del rag_citation_sink[rag_citation_count:]
                try:
                    parsed = invoke(fallback_no_tools_executor, fallback_usage, fallback=True)
                except Exception as no_tools_exc:
                    log_exception_without_details(logger, f"Tool-free fallback specialist {name} failed", no_tools_exc)
                    self.telemetry.record_agent(
                        name, started_at=started, prompt_text=payload, response_text="",
                        failed=True, **usage_details(fallback_usage),
                    )
                    raise RuntimeError(f"Falha controlada no especialista {name}.") from no_tools_exc

            self.telemetry.record_agent(
                name, started_at=started, prompt_text=payload,
                response_text=parsed.model_dump_json(), **usage_details(fallback_usage),
            )
            return parsed

    def route(self, message: str) -> RouteDecision:
        return self._invoke_controller("router", self.router, self.router_model_name, f"Data UTC: {temporal_context()}\n\nMensagem: {message}")

    def specialist(
        self,
        route: str,
        message: str,
        evidence: list,
        data: list[dict] | None = None,
        *,
        history: list[dict[str, str]] | None = None,
    ) -> SpecialistResult:
        selected = {"triage": self.triage, "standards": self.standards, "data": self.data, "performance": self.performance}[route]
        context = {
            "message": message,
            "conversation_history": history or [],
            "evidence": [_evidence_payload(item) for item in evidence],
            "database_data": data or [],
        }
        return self._invoke_specialist(
            route,
            selected,
            self.specialist_model_name,
            json.dumps(context, ensure_ascii=False, default=str),
            fallback_executor=self._specialist_fallback_agents.get(route),
            fallback_model=f"groq:{self.settings.groq_router_model}" if self._specialist_fallback_model else None,
            fallback_no_tools_executor=self._specialist_no_tools_fallback_agents.get(route),
        )

    def judge_result(
        self,
        specialist: SpecialistResult,
        evidence: list,
        data: list[dict] | None = None,
        *,
        route: str | None = None,
        question: str | None = None,
    ) -> JudgeVerdict:
        context = {
            "route": route,
            "question": question,
            "specialist_result": specialist.model_dump(mode="json"),
            "evidence": [_evidence_payload(item) for item in evidence],
            "database_data": data or [],
        }
        return self._invoke_controller("judge", self.judge, self.specialist_model_name, json.dumps(context, ensure_ascii=False, default=str))

    def summarize_session(self, messages: list[dict[str, Any]]) -> str:
        context = [
            {"role": message.get("role"), "content": str(message.get("content", ""))[:2000]}
            for message in messages
            if message.get("role") in {"user", "assistant"} and message.get("content")
        ]
        if not context:
            return ""
        prompt = ChatPromptTemplate.from_messages([
            ("system", SESSION_SUMMARY_PROMPT),
            ("user", "Mensagens da sessão:\n{input}"),
        ]) | self._structured_specialist(SessionSummary)
        result = self._invoke_controller(
            "session_summary",
            prompt,
            self.specialist_model_name,
            json.dumps(context, ensure_ascii=False),
        )
        return result.summary.strip()

    def format_answer(
        self,
        route: str,
        specialist: SpecialistResult | None,
        judge: JudgeVerdict | None,
        direct_reply: str | None = None,
        *,
        question: str | None = None,
    ) -> CorporateAnswer:
        context = {"route": route, "question": question, "specialist": specialist.model_dump(mode="json") if specialist else None, "judge": judge.model_dump(mode="json") if judge else None, "direct_reply": direct_reply}
        try:
            return self._invoke_controller(
                "orchestrator",
                self.orchestrator,
                self.router_model_name,
                json.dumps(context, ensure_ascii=False, default=str),
            )
        except RuntimeError:
            answer = (specialist.metrics_summary or {}).get("answer") if specialist else None
            if (
                route != "standards"
                or judge is None
                or not judge.approved
                or not isinstance(answer, str)
                or not answer.strip()
            ):
                raise
            logger.warning(
                "Orchestrator failed after judge approved standards response; returning validated specialist answer"
            )
            return CorporateAnswer(answer=answer.strip(), requires_human_validation=False)
