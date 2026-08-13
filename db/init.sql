CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS occurrence_drafts (
    id UUID PRIMARY KEY,
    tenant_id VARCHAR(80) NOT NULL,
    plant_id VARCHAR(80) NOT NULL,
    description TEXT NOT NULL,
    category VARCHAR(80) NOT NULL,
    volume_kg NUMERIC(14, 3),
    contamination_risk BOOLEAN NOT NULL,
    sanitation_level VARCHAR(12) NOT NULL CHECK (sanitation_level IN ('N1', 'N2', 'N3', 'INDEFINIDO')),
    technical_rationale TEXT NOT NULL,
    missing_information JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(32) NOT NULL CHECK (status IN ('AGUARDANDO_VALIDACAO', 'APROVADA', 'REJEITADA')),
    created_by VARCHAR(80) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    approved_by VARCHAR(80),
    approved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS occurrences (
    id UUID PRIMARY KEY,
    tenant_id VARCHAR(80) NOT NULL,
    plant_id VARCHAR(80) NOT NULL,
    description TEXT NOT NULL,
    category VARCHAR(80) NOT NULL,
    volume_kg NUMERIC(14, 3),
    contamination_risk BOOLEAN NOT NULL,
    sanitation_level VARCHAR(12) NOT NULL CHECK (sanitation_level IN ('N1', 'N2', 'N3', 'INDEFINIDO')),
    status VARCHAR(32) NOT NULL CHECK (status = 'REGISTRADA'),
    created_by VARCHAR(80) NOT NULL,
    approved_by VARCHAR(80) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    approved_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_occurrences_tenant_created_at ON occurrences (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_occurrences_tenant_category ON occurrences (tenant_id, category);

CREATE TABLE IF NOT EXISTS cooperative_service_levels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(80) NOT NULL,
    cooperative_name VARCHAR(160) NOT NULL,
    response_hours NUMERIC(10, 2) NOT NULL CHECK (response_hours >= 0),
    sla_met BOOLEAN NOT NULL,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cooperative_sla_tenant ON cooperative_service_levels (tenant_id, cooperative_name);
