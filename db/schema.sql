-- AMS Dashboard — Postgres schema (v0.2 draft)
--
-- Conventions:
--   • UUID primary keys (gen_random_uuid)
--   • snake_case identifiers
--   • TIMESTAMPTZ for all timestamps; DATE for calendar dates
--   • created_at / updated_at on mutable tables; trigger keeps updated_at fresh
--   • Soft delete: entity tables carry deleted_at TIMESTAMPTZ; uniqueness is
--     enforced via partial indexes (WHERE deleted_at IS NULL) so a name freed
--     by soft-delete can be reused. Pure join/history tables hard-delete.
--   • ON DELETE CASCADE for ownership; ON DELETE RESTRICT where deletes
--     should fail loudly
--
-- NOT in this schema:
--   • JIRA credentials → Secrets Manager
--   • App user identity → Cognito (linked via staff.cognito_sub)

-- ============================================================
-- EXTENSIONS
-- ============================================================
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- ENUMS
-- ============================================================
CREATE TYPE ams_level               AS ENUM ('Essential', 'Enhanced', 'Expert');
CREATE TYPE zabbix_status           AS ENUM ('Good', 'Issue');
CREATE TYPE software_version_status AS ENUM ('Latest', 'Supported', 'EOL');
CREATE TYPE analytic_frequency      AS ENUM ('Daily', 'Weekly', 'Monthly', 'Quarterly', 'Yearly');
CREATE TYPE activity_type           AS ENUM ('Meeting', 'Patch', 'Cert', 'Review', 'Other');
CREATE TYPE activity_priority       AS ENUM ('High', 'Medium', 'Low');
CREATE TYPE activity_status         AS ENUM ('scheduled', 'completed');
CREATE TYPE patch_execution_status  AS ENUM ('active', 'completed', 'aborted');

-- ============================================================
-- AUDIT HELPER
-- ============================================================
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 1. ORGANIZATIONS
--    Mirror of JIRA Service Management orgs + local-only metadata.
--    Caches JIRA-derived ticket counts to avoid live calls per page load.
-- ============================================================
CREATE TABLE organizations (
  id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  jira_org_id             TEXT NOT NULL,
  jira_name               TEXT NOT NULL,
  local_name              TEXT,
  ams_level               ams_level,
  zabbix_status           zabbix_status,
  help_desk_phone         TEXT,
  connection_guide_url    TEXT,
  notes                   TEXT,
  open_ticket_count       INTEGER,
  ticket_count_synced_at  TIMESTAMPTZ,
  last_ticket_sync_error  TEXT,
  jira_synced_at          TIMESTAMPTZ,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at              TIMESTAMPTZ
);
CREATE TRIGGER organizations_updated_at BEFORE UPDATE ON organizations
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE UNIQUE INDEX organizations_jira_org_id_unique
  ON organizations(jira_org_id) WHERE deleted_at IS NULL;
CREATE INDEX organizations_ams_level_idx ON organizations(ams_level)
  WHERE ams_level IS NOT NULL AND deleted_at IS NULL;

-- ============================================================
-- 2. ORG USERS
-- ============================================================
CREATE TABLE org_users (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  jira_account_id TEXT NOT NULL,
  display_name    TEXT,
  email           TEXT,
  role            TEXT,
  alerts_enabled  BOOLEAN NOT NULL DEFAULT FALSE,
  is_primary      BOOLEAN NOT NULL DEFAULT FALSE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at      TIMESTAMPTZ
);
CREATE TRIGGER org_users_updated_at BEFORE UPDATE ON org_users
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE UNIQUE INDEX org_users_org_jira_account_unique
  ON org_users(organization_id, jira_account_id) WHERE deleted_at IS NULL;
CREATE INDEX org_users_org_idx ON org_users(organization_id) WHERE deleted_at IS NULL;

-- ============================================================
-- 3. ENVIRONMENTS  (per-org list; defaults DEV/TEST/PROD, extensible)
-- ============================================================
CREATE TABLE environments (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  name            TEXT NOT NULL,
  position        INTEGER NOT NULL DEFAULT 0,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at      TIMESTAMPTZ
);
CREATE UNIQUE INDEX environments_org_name_unique
  ON environments(organization_id, name) WHERE deleted_at IS NULL;
CREATE INDEX environments_org_idx ON environments(organization_id) WHERE deleted_at IS NULL;

-- ============================================================
-- 4. SOFTWARE CATALOG
-- ============================================================
CREATE TABLE software (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL,
  description TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at  TIMESTAMPTZ
);
CREATE TRIGGER software_updated_at BEFORE UPDATE ON software
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE UNIQUE INDEX software_name_unique
  ON software(name) WHERE deleted_at IS NULL;

CREATE TABLE software_versions (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  software_id UUID NOT NULL REFERENCES software(id) ON DELETE CASCADE,
  version     TEXT NOT NULL,
  status      software_version_status NOT NULL,
  position    INTEGER NOT NULL DEFAULT 0,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at  TIMESTAMPTZ
);
CREATE TRIGGER software_versions_updated_at BEFORE UPDATE ON software_versions
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE UNIQUE INDEX software_versions_software_version_unique
  ON software_versions(software_id, version) WHERE deleted_at IS NULL;
-- At most one live version per software is flagged Latest.
CREATE UNIQUE INDEX software_versions_one_latest
  ON software_versions(software_id)
  WHERE status = 'Latest' AND deleted_at IS NULL;

CREATE TABLE software_releases (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  software_version_id UUID NOT NULL REFERENCES software_versions(id) ON DELETE CASCADE,
  release_name        TEXT NOT NULL,
  released_on         DATE,
  position            INTEGER NOT NULL DEFAULT 0,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at          TIMESTAMPTZ
);
CREATE UNIQUE INDEX software_releases_version_name_unique
  ON software_releases(software_version_id, release_name) WHERE deleted_at IS NULL;
CREATE INDEX software_releases_version_idx
  ON software_releases(software_version_id, position) WHERE deleted_at IS NULL;

-- ============================================================
-- 5. BASKETS  (logical software bundles)
-- ============================================================
CREATE TABLE baskets (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL,
  description TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at  TIMESTAMPTZ
);
CREATE TRIGGER baskets_updated_at BEFORE UPDATE ON baskets
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE UNIQUE INDEX baskets_name_unique
  ON baskets(name) WHERE deleted_at IS NULL;

CREATE TABLE basket_software (
  basket_id           UUID NOT NULL REFERENCES baskets(id) ON DELETE CASCADE,
  software_id         UUID NOT NULL REFERENCES software(id) ON DELETE RESTRICT,
  software_version_id UUID NOT NULL REFERENCES software_versions(id) ON DELETE RESTRICT,
  software_release_id UUID REFERENCES software_releases(id) ON DELETE RESTRICT,
  PRIMARY KEY (basket_id, software_id)
);
CREATE INDEX basket_software_software_idx ON basket_software(software_id);

-- ============================================================
-- 6. SERVERS
-- ============================================================
CREATE TABLE servers (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  environment_id  UUID NOT NULL REFERENCES environments(id) ON DELETE CASCADE,
  name            TEXT NOT NULL,
  notes           TEXT,
  cert_expires_on DATE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at      TIMESTAMPTZ
);
CREATE TRIGGER servers_updated_at BEFORE UPDATE ON servers
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE UNIQUE INDEX servers_env_name_unique
  ON servers(environment_id, name) WHERE deleted_at IS NULL;
CREATE INDEX servers_env_idx ON servers(environment_id) WHERE deleted_at IS NULL;
CREATE INDEX servers_cert_idx ON servers(cert_expires_on)
  WHERE cert_expires_on IS NOT NULL AND deleted_at IS NULL;

CREATE TABLE server_baskets (
  server_id UUID NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
  basket_id UUID NOT NULL REFERENCES baskets(id) ON DELETE CASCADE,
  PRIMARY KEY (server_id, basket_id)
);
CREATE INDEX server_baskets_basket_idx ON server_baskets(basket_id);

-- What's actually installed on each server. Drives Needs-Patching evaluation.
CREATE TABLE server_installed_software (
  server_id           UUID NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
  software_id         UUID NOT NULL REFERENCES software(id) ON DELETE RESTRICT,
  software_version_id UUID NOT NULL REFERENCES software_versions(id) ON DELETE RESTRICT,
  software_release_id UUID REFERENCES software_releases(id) ON DELETE RESTRICT,
  recorded_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (server_id, software_id)
);

-- ============================================================
-- 7. PATCH GROUPS  (reusable step lists)
-- ============================================================
CREATE TABLE patch_groups (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name       TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at TIMESTAMPTZ
);
CREATE TRIGGER patch_groups_updated_at BEFORE UPDATE ON patch_groups
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE UNIQUE INDEX patch_groups_name_unique
  ON patch_groups(name) WHERE deleted_at IS NULL;

CREATE TABLE patch_group_steps (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patch_group_id UUID NOT NULL REFERENCES patch_groups(id) ON DELETE CASCADE,
  step_num       INTEGER NOT NULL,
  description    TEXT NOT NULL DEFAULT '',
  est_time       TEXT,
  per_server     BOOLEAN NOT NULL DEFAULT FALSE,
  UNIQUE (patch_group_id, step_num)
);

-- ============================================================
-- 8. PATCH PLANS  (basket + ordered groups)
-- ============================================================
CREATE TABLE patch_plans (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name       TEXT NOT NULL,
  basket_id  UUID REFERENCES baskets(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at TIMESTAMPTZ
);
CREATE TRIGGER patch_plans_updated_at BEFORE UPDATE ON patch_plans
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE UNIQUE INDEX patch_plans_name_unique
  ON patch_plans(name) WHERE deleted_at IS NULL;

CREATE TABLE patch_plan_groups (
  patch_plan_id  UUID NOT NULL REFERENCES patch_plans(id) ON DELETE CASCADE,
  patch_group_id UUID NOT NULL REFERENCES patch_groups(id) ON DELETE RESTRICT,
  position       INTEGER NOT NULL,
  PRIMARY KEY (patch_plan_id, patch_group_id)
);

-- ============================================================
-- 9. PATCH EXECUTIONS  (active runs against (org, env))
-- ============================================================
CREATE TABLE patch_executions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patch_plan_id   UUID REFERENCES patch_plans(id) ON DELETE SET NULL,
  basket_id       UUID NOT NULL REFERENCES baskets(id) ON DELETE RESTRICT,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  environment_id  UUID NOT NULL REFERENCES environments(id) ON DELETE CASCADE,
  status          patch_execution_status NOT NULL DEFAULT 'active',
  patch_date      DATE,
  started_at      TIMESTAMPTZ,
  completed_at    TIMESTAMPTZ,
  total_time      TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at      TIMESTAMPTZ
);
CREATE TRIGGER patch_executions_updated_at BEFORE UPDATE ON patch_executions
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE INDEX patch_executions_status_idx ON patch_executions(status) WHERE deleted_at IS NULL;
CREATE INDEX patch_executions_org_env_idx
  ON patch_executions(organization_id, environment_id) WHERE deleted_at IS NULL;
-- Prototype enforces this: at most one active execution per (org, env, basket).
CREATE UNIQUE INDEX patch_executions_one_active
  ON patch_executions(organization_id, environment_id, basket_id)
  WHERE status = 'active' AND deleted_at IS NULL;

-- Snapshot of plan steps at execution time, so plan edits don't mutate history.
CREATE TABLE patch_execution_steps (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patch_execution_id UUID NOT NULL REFERENCES patch_executions(id) ON DELETE CASCADE,
  step_num           INTEGER NOT NULL,
  description        TEXT NOT NULL DEFAULT '',
  est_time           TEXT,
  per_server         BOOLEAN NOT NULL DEFAULT FALSE,
  started_at         TIMESTAMPTZ,
  finished_at        TIMESTAMPTZ,
  total_time         TEXT,
  done               BOOLEAN NOT NULL DEFAULT FALSE,
  UNIQUE (patch_execution_id, step_num)
);
CREATE INDEX patch_execution_steps_exec_idx ON patch_execution_steps(patch_execution_id);

CREATE TABLE patch_execution_aborts (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patch_execution_id UUID NOT NULL REFERENCES patch_executions(id) ON DELETE CASCADE,
  attempt_num        INTEGER NOT NULL,
  attempt_date       DATE,
  elapsed            TEXT,
  steps_completed    INTEGER NOT NULL DEFAULT 0,
  total_steps        INTEGER NOT NULL DEFAULT 0,
  notes              TEXT NOT NULL,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (patch_execution_id, attempt_num)
);

-- ============================================================
-- 10. PATCH HISTORY
--     software_name denormalized so renaming software later
--     doesn't rewrite the historical record.
-- ============================================================
CREATE TABLE patch_history (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id    UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  environment_id     UUID NOT NULL REFERENCES environments(id) ON DELETE CASCADE,
  patch_execution_id UUID REFERENCES patch_executions(id) ON DELETE SET NULL,
  patched_on         DATE NOT NULL,
  software_id        UUID REFERENCES software(id) ON DELETE SET NULL,
  software_name      TEXT NOT NULL,
  from_release       TEXT,
  to_release         TEXT NOT NULL,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX patch_history_org_env_idx
  ON patch_history(organization_id, environment_id, patched_on DESC);

-- ============================================================
-- 11. ANALYTICS
-- ============================================================
CREATE TABLE analytic_definitions (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name       TEXT NOT NULL,
  frequency  analytic_frequency NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at TIMESTAMPTZ
);
CREATE TRIGGER analytic_definitions_updated_at BEFORE UPDATE ON analytic_definitions
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE UNIQUE INDEX analytic_definitions_name_unique
  ON analytic_definitions(name) WHERE deleted_at IS NULL;

CREATE TABLE customer_analytics (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  environment_id         UUID NOT NULL REFERENCES environments(id) ON DELETE CASCADE,
  analytic_definition_id UUID NOT NULL REFERENCES analytic_definitions(id) ON DELETE RESTRICT,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at             TIMESTAMPTZ
);
CREATE UNIQUE INDEX customer_analytics_org_env_def_unique
  ON customer_analytics(organization_id, environment_id, analytic_definition_id)
  WHERE deleted_at IS NULL;
CREATE INDEX customer_analytics_org_idx
  ON customer_analytics(organization_id) WHERE deleted_at IS NULL;

-- Captured analytic values. value is NUMERIC since the use cases are all
-- numeric (record counts, peak CPU/disk/memory). description holds the
-- per-capture context. Adding columns later is a trivial ALTER TABLE.
CREATE TABLE customer_analytic_history (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_analytic_id UUID NOT NULL REFERENCES customer_analytics(id) ON DELETE CASCADE,
  captured_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  value                NUMERIC,
  description          TEXT,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX customer_analytic_history_cai_idx
  ON customer_analytic_history(customer_analytic_id, captured_at DESC);

-- ============================================================
-- 12. STAFF (IMT)
--     Single population: SMEs and app users are the same people.
--     cognito_sub links a row to its Cognito identity once SSO is in.
-- ============================================================
CREATE TABLE staff (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name         TEXT NOT NULL,
  email        TEXT,
  phone        TEXT,
  cognito_sub  TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at   TIMESTAMPTZ
);
CREATE TRIGGER staff_updated_at BEFORE UPDATE ON staff
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE UNIQUE INDEX staff_cognito_sub_unique
  ON staff(cognito_sub) WHERE cognito_sub IS NOT NULL AND deleted_at IS NULL;
CREATE INDEX staff_email_idx ON staff(email)
  WHERE email IS NOT NULL AND deleted_at IS NULL;

CREATE TABLE staff_sme_organizations (
  staff_id        UUID NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  PRIMARY KEY (staff_id, organization_id)
);
CREATE INDEX staff_sme_orgs_org_idx ON staff_sme_organizations(organization_id);

-- ============================================================
-- 13. ACTIVITIES
-- ============================================================
CREATE TABLE activities (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name              TEXT NOT NULL,
  scheduled_at      TIMESTAMPTZ NOT NULL,
  organization_id   UUID REFERENCES organizations(id) ON DELETE SET NULL,
  assigned_staff_id UUID REFERENCES staff(id) ON DELETE SET NULL,
  type              activity_type NOT NULL DEFAULT 'Meeting',
  priority          activity_priority NOT NULL DEFAULT 'Medium',
  duration          TEXT,
  notes             TEXT,
  status            activity_status NOT NULL DEFAULT 'scheduled',
  completed_at      TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at        TIMESTAMPTZ
);
CREATE TRIGGER activities_updated_at BEFORE UPDATE ON activities
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE INDEX activities_scheduled_idx ON activities(scheduled_at)
  WHERE status = 'scheduled' AND deleted_at IS NULL;
CREATE INDEX activities_org_idx ON activities(organization_id) WHERE deleted_at IS NULL;
CREATE INDEX activities_staff_idx ON activities(assigned_staff_id) WHERE deleted_at IS NULL;
