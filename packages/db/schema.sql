-- ============================================================
-- AEC Platform — Core shared schema
-- Referenced by all modules. Managed via Alembic migrations.
-- This file is the canonical reference — changes here must be
-- mirrored in an Alembic migration.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS vector;

-- ------------------------------------------------------------
-- Organizations (tenants)
-- ------------------------------------------------------------
CREATE TABLE organizations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  plan TEXT NOT NULL DEFAULT 'starter',
  modules JSONB DEFAULT '[]',
  settings JSONB DEFAULT '{}',
  country_code CHAR(2) DEFAULT 'VN',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ------------------------------------------------------------
-- Users
-- ------------------------------------------------------------
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  full_name TEXT,
  avatar_url TEXT,
  preferred_language TEXT DEFAULT 'vi',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ------------------------------------------------------------
-- Organization membership
-- ------------------------------------------------------------
CREATE TABLE org_members (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(organization_id, user_id)
);
CREATE INDEX ix_org_members_user ON org_members(user_id);

-- ------------------------------------------------------------
-- Projects
-- ------------------------------------------------------------
CREATE TABLE projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  type TEXT,
  status TEXT DEFAULT 'active',
  address JSONB,
  area_sqm NUMERIC,
  floors INTEGER,
  budget_vnd BIGINT,
  start_date DATE,
  end_date DATE,
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_projects_org ON projects(organization_id);

-- ------------------------------------------------------------
-- Files (shared across modules)
-- ------------------------------------------------------------
CREATE TABLE files (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  storage_key TEXT NOT NULL,
  mime_type TEXT,
  size_bytes BIGINT,
  source_module TEXT,
  processing_status TEXT DEFAULT 'pending',
  extracted_metadata JSONB DEFAULT '{}',
  created_by UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_files_org_project ON files(organization_id, project_id);

-- ------------------------------------------------------------
-- Embeddings (pgvector)
-- ------------------------------------------------------------
CREATE TABLE embeddings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  source_module TEXT NOT NULL,
  source_id UUID NOT NULL,
  chunk_index INTEGER,
  content TEXT NOT NULL,
  embedding vector(3072),
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_embeddings_source ON embeddings(organization_id, source_module, source_id);
CREATE INDEX ix_embeddings_vec ON embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ------------------------------------------------------------
-- AI Jobs
-- ------------------------------------------------------------
CREATE TABLE ai_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  module TEXT NOT NULL,
  job_type TEXT NOT NULL,
  status TEXT DEFAULT 'queued',
  input JSONB,
  output JSONB,
  error TEXT,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_ai_jobs_org_status ON ai_jobs(organization_id, status);

-- ============================================================
-- Row-level security: tenant isolation
-- Enforced via `app.current_org_id` set per-request by the API.
-- ============================================================
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE files ENABLE ROW LEVEL SECURITY;
ALTER TABLE embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_jobs ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_projects ON projects
  USING (organization_id = current_setting('app.current_org_id', true)::uuid);
CREATE POLICY tenant_isolation_files ON files
  USING (organization_id = current_setting('app.current_org_id', true)::uuid);
CREATE POLICY tenant_isolation_embeddings ON embeddings
  USING (organization_id = current_setting('app.current_org_id', true)::uuid);
CREATE POLICY tenant_isolation_ai_jobs ON ai_jobs
  USING (organization_id = current_setting('app.current_org_id', true)::uuid);

-- ============================================================
-- MODULE 5 — COSTPULSE (Estimation & Procurement Intelligence)
-- ============================================================

CREATE TABLE suppliers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,  -- NULL = platform-wide
  name TEXT NOT NULL,
  categories TEXT[] DEFAULT ARRAY[]::TEXT[],
  provinces TEXT[] DEFAULT ARRAY[]::TEXT[],
  contact JSONB DEFAULT '{}',
  verified BOOLEAN NOT NULL DEFAULT false,
  rating NUMERIC,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_suppliers_org ON suppliers(organization_id);
CREATE INDEX ix_suppliers_categories ON suppliers USING gin (categories);
CREATE INDEX ix_suppliers_provinces ON suppliers USING gin (provinces);

CREATE TABLE material_prices (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  material_code TEXT NOT NULL,
  name TEXT NOT NULL,
  category TEXT,
  unit TEXT NOT NULL,
  price_vnd NUMERIC NOT NULL,
  price_usd NUMERIC,
  province TEXT,
  source TEXT,
  effective_date DATE NOT NULL,
  expires_date DATE,
  supplier_id UUID REFERENCES suppliers(id) ON DELETE SET NULL,
  UNIQUE(material_code, province, effective_date)
);
CREATE INDEX ix_material_prices_code ON material_prices(material_code);
CREATE INDEX ix_material_prices_category ON material_prices(category);
CREATE INDEX ix_material_prices_province ON material_prices(province);
CREATE INDEX ix_material_prices_effective ON material_prices(effective_date);

CREATE TABLE estimates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'draft',
  total_vnd BIGINT,
  confidence TEXT,
  method TEXT,
  created_by UUID REFERENCES users(id) ON DELETE SET NULL,
  approved_by UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_estimates_org_project ON estimates(organization_id, project_id);
CREATE INDEX ix_estimates_status ON estimates(organization_id, status);

CREATE TABLE boq_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  estimate_id UUID NOT NULL REFERENCES estimates(id) ON DELETE CASCADE,
  parent_id UUID REFERENCES boq_items(id) ON DELETE CASCADE,
  sort_order INTEGER DEFAULT 0,
  code TEXT,
  description TEXT NOT NULL,
  unit TEXT,
  quantity NUMERIC,
  unit_price_vnd NUMERIC,
  total_price_vnd NUMERIC,
  material_code TEXT,
  source TEXT,
  notes TEXT
);
CREATE INDEX ix_boq_items_estimate ON boq_items(estimate_id, sort_order);
CREATE INDEX ix_boq_items_parent ON boq_items(parent_id);

CREATE TABLE rfqs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
  estimate_id UUID REFERENCES estimates(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  sent_to UUID[] DEFAULT ARRAY[]::UUID[],
  responses JSONB DEFAULT '[]',
  deadline DATE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_rfqs_org_project ON rfqs(organization_id, project_id);
CREATE INDEX ix_rfqs_status ON rfqs(organization_id, status);

CREATE TABLE price_alerts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  material_code TEXT NOT NULL,
  province TEXT,
  threshold_pct NUMERIC DEFAULT 5,
  last_price_vnd NUMERIC,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(organization_id, user_id, material_code, province)
);
CREATE INDEX ix_price_alerts_material ON price_alerts(material_code);

ALTER TABLE estimates ENABLE ROW LEVEL SECURITY;
ALTER TABLE boq_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE rfqs ENABLE ROW LEVEL SECURITY;
ALTER TABLE price_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE suppliers ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_estimates ON estimates
  USING (organization_id = current_setting('app.current_org_id', true)::uuid);
CREATE POLICY tenant_isolation_boq_items ON boq_items
  USING (EXISTS (SELECT 1 FROM estimates e WHERE e.id = boq_items.estimate_id
    AND e.organization_id = current_setting('app.current_org_id', true)::uuid));
CREATE POLICY tenant_isolation_rfqs ON rfqs
  USING (organization_id = current_setting('app.current_org_id', true)::uuid);
CREATE POLICY tenant_isolation_price_alerts ON price_alerts
  USING (organization_id = current_setting('app.current_org_id', true)::uuid);
CREATE POLICY tenant_visibility_suppliers ON suppliers
  USING (organization_id IS NULL
    OR organization_id = current_setting('app.current_org_id', true)::uuid);

-- ============================================================
-- MODULE 7 — BIDRADAR (Tender Intelligence)
-- ============================================================

CREATE TABLE tenders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source TEXT NOT NULL,
  external_id TEXT NOT NULL,
  title TEXT NOT NULL,
  issuer TEXT,
  type TEXT,
  budget_vnd BIGINT,
  currency TEXT DEFAULT 'VND',
  country_code CHAR(2) DEFAULT 'VN',
  province TEXT,
  disciplines TEXT[],
  project_types TEXT[],
  submission_deadline TIMESTAMPTZ,
  published_at TIMESTAMPTZ,
  description TEXT,
  raw_url TEXT,
  raw_payload JSONB,
  scraped_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(source, external_id)
);
CREATE INDEX ix_tenders_deadline ON tenders(submission_deadline);
CREATE INDEX ix_tenders_country_province ON tenders(country_code, province);
CREATE INDEX ix_tenders_disciplines ON tenders USING gin(disciplines);

CREATE TABLE firm_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL UNIQUE REFERENCES organizations(id) ON DELETE CASCADE,
  disciplines TEXT[],
  project_types TEXT[],
  provinces TEXT[],
  min_budget_vnd BIGINT,
  max_budget_vnd BIGINT,
  team_size INTEGER,
  active_capacity_pct NUMERIC,
  past_wins JSONB DEFAULT '[]',
  keywords TEXT[],
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE tender_matches (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  tender_id UUID NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
  match_score NUMERIC,
  estimated_value_vnd BIGINT,
  competition_level TEXT,
  win_probability NUMERIC,
  recommended_bid BOOLEAN,
  ai_recommendation JSONB,
  status TEXT DEFAULT 'new',  -- new | saved | pursuing | passed
  proposal_id UUID,
  reviewed_by UUID REFERENCES users(id) ON DELETE SET NULL,
  reviewed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(organization_id, tender_id)
);
CREATE INDEX ix_tender_matches_org_status ON tender_matches(organization_id, status);
CREATE INDEX ix_tender_matches_score ON tender_matches(organization_id, match_score DESC);

CREATE TABLE tender_digests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  week_start DATE NOT NULL,
  week_end DATE NOT NULL,
  top_match_ids UUID[],
  sent_to TEXT[],
  sent_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(organization_id, week_start)
);

ALTER TABLE firm_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE tender_matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE tender_digests ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_firm_profiles ON firm_profiles
  USING (organization_id = current_setting('app.current_org_id', true)::uuid);
CREATE POLICY tenant_isolation_tender_matches ON tender_matches
  USING (organization_id = current_setting('app.current_org_id', true)::uuid);
CREATE POLICY tenant_isolation_tender_digests ON tender_digests
  USING (organization_id = current_setting('app.current_org_id', true)::uuid);
