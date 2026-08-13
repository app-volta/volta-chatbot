"""Integração A2A autenticada com o sistema das cooperativas parceiras."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime

import httpx

from app.core.config import Settings
from app.db.models import CollectionRequest


class CooperativeA2AClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def request_collection(self, request: CollectionRequest) -> dict:
        if not self.settings.cooperative_a2a_base_url or not self.settings.cooperative_a2a_hmac_secret:
            raise RuntimeError("Integração A2A não configurada.")
        payload = {
            "protocol_version": "a2a-1.0",
            "event": "collection.requested",
            "sent_at": datetime.now(UTC).isoformat(),
            **request.model_dump(mode="json"),
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(
            self.settings.cooperative_a2a_hmac_secret.get_secret_value().encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        endpoint = f"{str(self.settings.cooperative_a2a_base_url).rstrip('/')}/a2a/collection-requests"
        response = httpx.post(
            endpoint,
            content=body,
            timeout=self.settings.a2a_timeout_seconds,
            headers={"content-type": "application/json", "x-volta-signature": f"sha256={signature}"},
        )
        response.raise_for_status()
        return response.json()
