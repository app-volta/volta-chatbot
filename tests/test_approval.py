from uuid import UUID

import pytest
from fastapi import HTTPException

from app.api.occurrences import approve_occurrence_draft
from app.core.auth import RequestIdentity

DRAFT = UUID("550e8400-e29b-41d4-a716-446655440010")
TENANT = "550e8400-e29b-41d4-a716-446655440001"
GESTOR = "550e8400-e29b-41d4-a716-446655440002"
AUTHOR = "550e8400-e29b-41d4-a716-446655440003"


class FakeRepository:
    def __init__(self, error=None):
        self.error = error
        self.args = None

    def approve_occurrence_draft(self, *args):
        self.args = args
        if self.error:
            raise self.error
        return DRAFT


class FakeTelemetry:
    def record_human_intervention(self, event):
        pass


def test_approval_rejects_missing_or_cross_tenant_draft_with_404():
    for error in (LookupError("missing"), LookupError("other tenant")):
        with pytest.raises(HTTPException) as exc:
            approve_occurrence_draft(DRAFT, RequestIdentity(TENANT, GESTOR, "GESTOR"), FakeRepository(error), FakeTelemetry())
        assert exc.value.status_code == 404


def test_approval_returns_409_for_processed_draft():
    with pytest.raises(HTTPException) as exc:
        approve_occurrence_draft(DRAFT, RequestIdentity(TENANT, GESTOR, "gestor"), FakeRepository(ValueError()), FakeTelemetry())
    assert exc.value.status_code == 409


def test_approval_fails_closed_for_non_gestor_without_calling_repository():
    repository = FakeRepository()
    with pytest.raises(HTTPException) as exc:
        approve_occurrence_draft(DRAFT, RequestIdentity(TENANT, GESTOR, "admin"), repository, FakeTelemetry())
    assert exc.value.status_code == 403
    assert repository.args is None


def test_approval_rejects_author_self_approval():
    with pytest.raises(HTTPException) as exc:
        approve_occurrence_draft(DRAFT, RequestIdentity(TENANT, AUTHOR, "gestor"), FakeRepository(PermissionError()), FakeTelemetry())
    assert exc.value.status_code == 403


def test_approval_passes_authenticated_tenant_and_user_to_repository():
    repository = FakeRepository()
    result = approve_occurrence_draft(DRAFT, RequestIdentity(TENANT, GESTOR, "GESTOR"), repository, FakeTelemetry())
    assert result.occurrence_id == DRAFT
    assert repository.args == (DRAFT, TENANT, GESTOR)
