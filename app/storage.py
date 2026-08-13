"""
Camada de Persistência Centralizada.
Contém os repositórios transacionais (PostgreSQL) e de sessão (MongoDB).
O FastAPI instancia e encerra esses pools durante o lifespan (main.py).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection

from app.models import ProposedOccurrence


# ==============================================================================
# POSTGRESQL (Transacional, RAG Tools e Ocorrências)
# ==============================================================================
class PostgresRepository:
    def __init__(self) -> None:
        self.pool = None

    def open(self, dsn: str) -> None:
        """Abre a pool de conexões (Chamado no lifespan do FastAPI)."""
        self.pool = ConnectionPool(
            conninfo=dsn,
            min_size=1,
            max_size=8,
            kwargs={"row_factory": dict_row, "prepare_threshold": None},
            open=True,
        )

    def close(self) -> None:
        """Encerra a pool (Chamado no teardown do lifespan)."""
        if self.pool is not None:
            self.pool.close()

    def healthcheck(self) -> bool:
        if self.pool is None:
            return False
        try:
            with self.pool.connection() as connection, connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return cursor.fetchone()["?column?"] == 1
        except Exception:
            return False

    def create_occurrence_draft(
        self, tenant_id: str, plant_id: str, created_by: str, proposal: ProposedOccurrence
    ) -> UUID:
        draft_id = uuid4()
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO occurrence_drafts (
                    id, tenant_id, plant_id, description, category, volume_kg,
                    contamination_risk, sanitation_level, technical_rationale,
                    missing_information, status, created_by, created_at
                ) VALUES (%(id)s, %(tenant_id)s, %(plant_id)s, %(description)s, %(category)s,
                    %(volume_kg)s, %(contamination_risk)s, %(sanitation_level)s,
                    %(technical_rationale)s, %(missing_information)s,
                    'AGUARDANDO_VALIDACAO', %(created_by)s, %(created_at)s)
                """,
                {
                    "id": draft_id,
                    "tenant_id": tenant_id,
                    "plant_id": plant_id,
                    "description": proposal.description,
                    "category": proposal.category,
                    "volume_kg": getattr(proposal, "estimated_volume_kg", 0.0),
                    "contamination_risk": getattr(proposal, "contamination_risk", False),
                    "sanitation_level": getattr(proposal, "sanitation_level", "N/A"),
                    "technical_rationale": getattr(proposal, "technical_rationale", ""),
                    "missing_information": getattr(proposal, "missing_information", ""),
                    "created_by": created_by,
                    "created_at": datetime.now(UTC),
                },
            )
        return draft_id

    def approve_occurrence_draft(self, draft_id: UUID, approved_by: str) -> UUID:
        occurrence_id = uuid4()
        now = datetime.now(UTC)
        with self.pool.connection() as connection, connection.transaction(), connection.cursor() as cursor:
            cursor.execute("SELECT * FROM occurrence_drafts WHERE id = %s FOR UPDATE", (draft_id,))
            draft = cursor.fetchone()
            if not draft:
                raise LookupError("Rascunho de ocorrência não encontrado.")
            if draft["status"] != "AGUARDANDO_VALIDACAO":
                raise ValueError("Este rascunho já foi processado.")

            cursor.execute(
                """
                INSERT INTO occurrences (
                    id, tenant_id, plant_id, description, category, volume_kg,
                    contamination_risk, sanitation_level, status, created_by,
                    approved_by, created_at, approved_at
                ) VALUES (%(id)s, %(tenant_id)s, %(plant_id)s, %(description)s, %(category)s,
                    %(volume_kg)s, %(contamination_risk)s, %(sanitation_level)s,
                    'REGISTRADA', %(created_by)s, %(approved_by)s, %(created_at)s, %(approved_at)s)
                """,
                {**draft, "id": occurrence_id, "approved_by": approved_by, "approved_at": now},
            )
            cursor.execute(
                "UPDATE occurrence_drafts SET status = 'APROVADA', approved_by = %s, approved_at = %s WHERE id = %s",
                (approved_by, now, draft_id),
            )
        return occurrence_id

    def consultar_metricas_esg(self, month: int, year: int, tenant_id: str | None = None) -> list[dict]:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT category,
                       COUNT(*) AS ocorrencias_registradas,
                       COALESCE(SUM(volume_kg), 0) AS volume_total_kg,
                       COUNT(*) FILTER (WHERE contamination_risk) AS ocorrencias_com_risco
                FROM occurrences
                WHERE created_at >= make_date(%s, %s, 1)
                  AND created_at < make_date(%s, %s, 1) + INTERVAL '1 month'
                  AND (%s IS NULL OR tenant_id = %s)
                GROUP BY category
                ORDER BY volume_total_kg DESC
                """,
                (year, month, year, month, tenant_id, tenant_id),
            )
            rows = cursor.fetchall()
            return [{**row, "volume_total_kg": float(row["volume_total_kg"])} for row in rows]

    def consultar_performance_cooperativas(self, tenant_id: str | None = None) -> list[dict]:
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT cooperative_name,
                       COUNT(*) AS coletas_concluidas,
                       ROUND(AVG(response_hours)::numeric, 2) AS tempo_medio_resposta_horas,
                       ROUND(AVG(CASE WHEN sla_met THEN 1 ELSE 0 END)::numeric * 100, 2) AS cumprimento_sla_percentual
                FROM cooperative_service_levels
                WHERE (%s IS NULL OR tenant_id = %s)
                GROUP BY cooperative_name
                ORDER BY cumprimento_sla_percentual DESC, tempo_medio_resposta_horas ASC
                """,
                (tenant_id, tenant_id),
            )
            return cursor.fetchall()


# ==============================================================================
# MONGODB (Sessões e Memória de Chat)
# ==============================================================================
class SessionRepository:
    def __init__(self) -> None:
        self.client = None
        self.sessions: Collection = None
        self.messages: Collection = None
        self.audit: Collection = None

    def open(self, mongo_uri: str) -> None:
        # Trata e remove a exigência de replicaSet se ela estiver presente na URI do Mongo
        clean_uri = re.sub(r"[?&]replicaSet=[^&]*", "", mongo_uri)
        if clean_uri.endswith("?"):
            clean_uri = clean_uri[:-1]

        self.client = MongoClient(
            clean_uri,
            directConnection=True,
            serverSelectionTimeoutMS=5000,
            appname="volta-api",
        )
        database = self.client.get_database()
        self.sessions = database["sessions"]
        self.messages = database["chat_messages"]
        self.audit = database["security_audit"]

    def ensure_indexes(self) -> None:
        if self.sessions is None:
            return
        self.sessions.create_index([("session_id", ASCENDING)], unique=True)
        self.sessions.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
        self.messages.create_index([("session_id", ASCENDING), ("created_at", ASCENDING)])
        self.audit.create_index([("created_at", DESCENDING)])

    def create_session(self, tenant_id: str, user_id: str) -> dict:
        now = datetime.now(UTC)
        document = {
            "session_id": str(uuid4()),
            "tenant_id": tenant_id,
            "user_id": user_id,
            "created_at": now,
            "closed_at": None,
        }
        self.sessions.insert_one(document)
        return document

    def ensure_session_owner(self, session_id: str, tenant_id: str, user_id: str) -> None:
        found = self.sessions.find_one(
            {"session_id": session_id, "tenant_id": tenant_id, "user_id": user_id, "closed_at": None},
            {"_id": 1},
        )
        if not found:
            raise PermissionError("Sessão inexistente, encerrada ou não autorizada para este usuário.")

    def append_message(self, session_id: str, role: str, content: str, request_id: str) -> None:
        if role not in {"user", "assistant", "system"}:
            raise ValueError("Role inválida para o histórico.")
        self.messages.insert_one(
            {
                "session_id": session_id,
                "role": role,
                "content": content,
                "request_id": request_id,
                "created_at": datetime.now(UTC),
            }
        )

    def recent_history(self, session_id: str, limit: int = 8) -> list[dict]:
        cursor = self.messages.find({"session_id": session_id}).sort("created_at", DESCENDING).limit(limit)
        return list(
            reversed([{key: value for key, value in message.items() if key != "_id"} for message in cursor])
        )

    def audit_security_event(self, session_id: str, event: str) -> None:
        self.audit.insert_one({"session_id": session_id, "event": event, "created_at": datetime.now(UTC)})

    def healthcheck(self) -> bool:
        if self.client is None:
            return False
        try:
            self.client.admin.command("ping")
            return True
        except Exception:
            return False

    def close(self) -> None:
        if self.client is not None:
            self.client.close()


# Instâncias globais
db_postgres = PostgresRepository()
db_mongo = SessionRepository()