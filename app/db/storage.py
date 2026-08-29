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

from app.db.models import ProposedOccurrence


def _company_id_from_tenant(tenant_id: str | None) -> int | None:
    """Mapeia o tenant do chatbot para company_id no schema compartilhado."""
    if tenant_id is None:
        return None
    try:
        return int(tenant_id)
    except (TypeError, ValueError):
        return None


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
        
    def get_incident_history_by_area(self, area_id: int) -> list[dict]:
        """Busca o historico de peso de lixo de uma cacamba especifica para treinar a IA."""
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    DATE(registered_at) AS data_registro,
                    SUM(estimated_quantity) AS peso_total_dia
                FROM incident
                WHERE area_id = %s AND estimated_quantity IS NOT NULL
                GROUP BY DATE(registered_at)
                ORDER BY data_registro ASC;
                """,
                (area_id,)
            )
            # Formata a data para string e o peso para float para facilitar o trabalho do Pandas
            return [{"data_registro": str(row["data_registro"]), "peso_total_dia": float(row["peso_total_dia"])} for row in cursor.fetchall()]    

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
        self, company_id: int, area_id: int, user_id: int, ai_data: dict
    ) -> int:
        """Salva o rascunho do incidente e atrela o laudo da IA a ele."""
        with self.pool.connection() as connection, connection.transaction(), connection.cursor() as cursor:
            # 1. Cria o incidente com status pendente (Aguardando validação humana)
            cursor.execute(
                """
                INSERT INTO incident (
                    company_id, area_id, user_id, 
                    contamination_level, estimated_quantity, status, registered_at
                ) VALUES (
                    %(company_id)s, %(area_id)s, %(user_id)s, 
                    %(contamination)s, %(volume)s, 'AGUARDANDO_VALIDACAO', CURRENT_TIMESTAMP
                ) RETURNING id;
                """,
                {
                    "company_id": company_id,
                    "area_id": area_id,
                    "user_id": user_id,
                    "contamination": ai_data.get("ai_contamination_level", "N/A"),
                    "volume": ai_data.get("estimated_quantity_kg", 0.0),
                }
            )
            incident_id = cursor.fetchone()["id"]

            # 2. Salva o laudo gerado pelo Gemini na tabela ai_report
            cursor.execute(
                """
                INSERT INTO ai_report (
                    incident_id, detected_waste_type, ai_contamination_level, 
                    recommendations, report_text, generated_at
                ) VALUES (
                    %(incident_id)s, %(detected)s, %(contamination)s, 
                    %(recs)s, %(report)s, CURRENT_TIMESTAMP
                );
                """,
                {
                    "incident_id": incident_id,
                    "detected": ai_data.get("detected_waste_type", ""),
                    "contamination": ai_data.get("ai_contamination_level", ""),
                    "recs": ai_data.get("recommendations", ""),
                    "report": ai_data.get("report_text", ""),
                }
            )
            return incident_id

    def approve_occurrence_draft(self, draft_id: int) -> int:
        """Oficializa o registro mudando o status para REGISTRADA."""
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE incident SET status = 'REGISTRADA' WHERE id = %s RETURNING id",
                (draft_id,)
            )
            updated = cursor.fetchone()
            if not updated:
                raise LookupError("Rascunho não encontrado.")
            return updated["id"]
        
    def get_all_drafts(self) -> list[dict]:
        """Busca os incidentes pendentes junto com o laudo da IA."""
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT i.id, i.status, i.estimated_quantity, 
                       a.detected_waste_type, a.report_text
                FROM incident i
                JOIN ai_report a ON i.id = a.incident_id
                WHERE i.status = 'AGUARDANDO_VALIDACAO'
                ORDER BY i.registered_at DESC
                """
            )
            return cursor.fetchall()    
        
    def consultar_metricas_esg(self, month: int, year: int, tenant_id: str | None = None) -> list[dict]:
        company_id = _company_id_from_tenant(tenant_id)
        if tenant_id is not None and company_id is None:
            return []
        period = f"{year:04d}-{month:02d}"
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT company_id,
                       period,
                       COALESCE(total_waste_kg, 0) AS total_waste_kg,
                       COALESCE(total_recycled_kg, 0) AS total_recycled_kg,
                       COALESCE(recycling_percentage, 0) AS recycling_percentage,
                       calculated_at
                FROM esg_metric
                WHERE period = %s
                  AND (%s IS NULL OR company_id = %s)
                ORDER BY company_id
                """,
                (period, company_id, company_id),
            )
            rows = cursor.fetchall()
            return [
                {
                    **row,
                    "total_waste_kg": float(row["total_waste_kg"]),
                    "total_recycled_kg": float(row["total_recycled_kg"]),
                    "recycling_percentage": float(row["recycling_percentage"]),
                }
                for row in rows
            ]

    def consultar_performance_cooperativas(self, tenant_id: str | None = None) -> list[dict]:
        company_id = _company_id_from_tenant(tenant_id)
        if tenant_id is not None and company_id is None:
            return []
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.name AS cooperative_name,
                       COUNT(*) FILTER (WHERE col.current_status IN ('COMPLETED', 'COLLECTED', 'DONE')) AS coletas_concluidas,
                       ROUND(AVG(EXTRACT(EPOCH FROM (col.scheduled_date - col.request_date)))::numeric / 3600, 2) AS tempo_medio_resposta_horas,
                       ROUND(AVG(CASE WHEN col.current_status IN ('COMPLETED', 'COLLECTED', 'DONE') THEN 1 ELSE 0 END)::numeric * 100, 2) AS cumprimento_sla_percentual
                FROM collection col
                JOIN cooperative c ON c.id = col.cooperative_id
                JOIN incident i ON i.id = col.incident_id
                WHERE (%s IS NULL OR i.company_id = %s)
                GROUP BY c.name
                ORDER BY cumprimento_sla_percentual DESC, tempo_medio_resposta_horas ASC
                """,
                (company_id, company_id),
            )
            return cursor.fetchall()
        
    def get_recent_incidents(self, limit: int = 5):
            """Busca as ultimas ocorrencias para analise da IA."""
            with self.pool.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT employee_description, contamination_level, estimated_quantity, priority 
                    FROM incident 
                    ORDER BY registered_at DESC 
                    LIMIT %s;
                    """,
                    (limit,)
                )
                columns = [col.name for col in cursor.description]
                results = [dict(zip(columns, row)) for row in cursor.fetchall()]
                return results            


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
            
    def save_incident(self, area_id: int, waste_type_id: int, photo_url: str, employee_description: str, contamination_level: str, estimated_quantity: float, priority: str, status: str = "REGISTRADA") -> int:
        """Salva a ocorrencia confirmada no banco PostgreSQL."""
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO incident (
                    area_id,
                    waste_type_id,
                    photo_url,
                    employee_description,
                    contamination_level,
                    estimated_quantity,
                    priority,
                    status,
                    registered_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                RETURNING id;
                """,
                (
                    area_id,
                    waste_type_id,
                    photo_url,
                    employee_description,
                    contamination_level,
                    estimated_quantity,
                    priority,
                    status,
                )
            )
            incident_id = cursor.fetchone()[0]
            connection.commit()
            return incident_id    
        
                     
# Instâncias globais
db_postgres = PostgresRepository()
db_mongo = SessionRepository()
