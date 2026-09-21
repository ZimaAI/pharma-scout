-- PharmaScope V1 PostgreSQL reference schema.
-- NOT executed in PostgreSQL during document generation. Convert to Alembic and test.
BEGIN;

CREATE TABLE app_user (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text NOT NULL UNIQUE,
  display_name text NOT NULL,
  password_hash text NOT NULL,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE workspace (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  timezone text NOT NULL DEFAULT 'Asia/Shanghai',
  settings jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE membership (
 workspace_id uuid NOT NULL REFERENCES workspace(id), user_id uuid NOT NULL REFERENCES app_user(id),
 role text NOT NULL CHECK(role IN ('reader','analyst','reviewer','admin')), enabled boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(workspace_id,user_id)
);

CREATE TABLE app_session (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES app_user(id),
  token_hash text NOT NULL UNIQUE,
  csrf_hash text NOT NULL,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE drug (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  display_name text NOT NULL,
  development_code text,
  description text,
  indications jsonb NOT NULL DEFAULT '[]'::jsonb,
  targets jsonb NOT NULL DEFAULT '[]'::jsonb,
  revision integer NOT NULL DEFAULT 1 CHECK(revision>0),
  archived boolean NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id)
);

CREATE TABLE drug_alias (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  drug_id uuid NOT NULL,
  alias text NOT NULL,
  normalized_alias text NOT NULL,
  namespace text NOT NULL,
  status text NOT NULL DEFAULT 'pending',
  evidence_id uuid,
  note text NOT NULL,
  proposed_by uuid NOT NULL REFERENCES app_user(id),
  reviewed_by uuid REFERENCES app_user(id),
  reviewed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  CHECK (status IN ('pending', 'approved', 'rejected', 'revoked')),
  UNIQUE(workspace_id,drug_id,namespace,normalized_alias)
);

CREATE TABLE source_record (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  source text NOT NULL,
  external_id text NOT NULL,
  kind text NOT NULL,
  canonical_url text NOT NULL,
  current_snapshot_id uuid,
  current_observation_id uuid,
  next_observation_seq bigint NOT NULL DEFAULT 0,
  current_projection jsonb NOT NULL DEFAULT '{}'::jsonb,
  is_demo boolean NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  CHECK (source IN ('ctgov', 'pubmed')),
  CHECK (kind IN ('trial', 'publication')),
  UNIQUE(workspace_id,source,external_id)
);

CREATE TABLE source_snapshot (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  record_id uuid NOT NULL,
  content_hash char(64) NOT NULL,
  normalizer_version text NOT NULL,
  raw_payload jsonb NOT NULL,
  normalized jsonb NOT NULL,
  source_updated jsonb NOT NULL DEFAULT '{}'::jsonb,
  first_observed_at timestamptz NOT NULL,
  is_demo boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  UNIQUE(workspace_id,record_id,content_hash,normalizer_version)
);

CREATE TABLE source_observation (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  record_id uuid NOT NULL,
  snapshot_id uuid,
  observation_seq bigint NOT NULL CHECK(observation_seq>0),
  fetched_at timestamptz NOT NULL,
  outcome text NOT NULL,
  error_code text,
  operation_key text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  CHECK (outcome IN ('baseline', 'changed', 'unchanged', 'unavailable', 'failed')),
  UNIQUE(workspace_id,record_id,observation_seq),
  UNIQUE(workspace_id,record_id,operation_key)
);

CREATE TABLE source_sync_state (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  source text NOT NULL,
  query_fingerprint char(64) NOT NULL,
  scope jsonb NOT NULL DEFAULT '{}'::jsonb,
  cursor text,
  complete_watermark timestamptz,
  last_success_at timestamptz,
  last_error_code text,
  revision integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  CHECK (source IN ('ctgov', 'pubmed')),
  UNIQUE(workspace_id,source,query_fingerprint)
);

CREATE TABLE entity_link (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  record_id uuid NOT NULL,
  drug_id uuid NOT NULL,
  relation text NOT NULL,
  status text NOT NULL DEFAULT 'pending',
  evidence_id uuid,
  note text NOT NULL,
  proposed_by uuid NOT NULL REFERENCES app_user(id),
  reviewed_by uuid REFERENCES app_user(id),
  reviewed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  CHECK (relation IN ('investigational', 'comparator', 'background', 'unspecified', 'mentions')),
  CHECK (status IN ('pending', 'approved', 'rejected', 'revoked')),
  UNIQUE(workspace_id,record_id,drug_id,relation)
);

CREATE TABLE evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  snapshot_id uuid NOT NULL,
  locator jsonb NOT NULL,
  quoted_text text NOT NULL,
  snippet_hash char(64) NOT NULL,
  original_language text NOT NULL,
  translation_text text,
  extractor_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id)
);

CREATE TABLE intelligence_event (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  record_id uuid NOT NULL,
  category text NOT NULL,
  title text NOT NULL,
  latest_revision_id uuid,
  updated_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  UNIQUE(workspace_id,record_id,category)
);

CREATE TABLE event_revision (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  event_id uuid NOT NULL,
  revision_no integer NOT NULL CHECK(revision_no>0),
  before_observation_id uuid NOT NULL,
  after_observation_id uuid NOT NULL,
  changes jsonb NOT NULL DEFAULT '[]'::jsonb,
  evidence_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  severity text NOT NULL,
  observed_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  CHECK (severity IN ('info', 'important', 'correction')),
  UNIQUE(workspace_id,event_id,revision_no),
  UNIQUE(workspace_id,event_id,before_observation_id,after_observation_id),
  CHECK(before_observation_id<>after_observation_id)
);

CREATE TABLE job (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  kind text NOT NULL,
  state text NOT NULL DEFAULT 'queued',
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  progress jsonb NOT NULL DEFAULT '{}'::jsonb,
  coverage jsonb NOT NULL DEFAULT '[]'::jsonb,
  attempt integer NOT NULL DEFAULT 0 CHECK(attempt>=0),
  available_at timestamptz NOT NULL DEFAULT now(),
  owner_token uuid,
  lease_expires_at timestamptz,
  error_code text,
  updated_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  CHECK (kind IN ('ingest', 'research', 'delivery')),
  CHECK (state IN ('queued', 'running', 'retry_wait', 'succeeded', 'failed', 'cancelled'))
);

CREATE TABLE research_run (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  created_by uuid NOT NULL REFERENCES app_user(id),
  job_id uuid,
  question text NOT NULL,
  status text NOT NULL DEFAULT 'queued',
  runtime_mode text NOT NULL,
  frozen_request jsonb NOT NULL,
  research_state jsonb NOT NULL DEFAULT '{}'::jsonb,
  budget jsonb NOT NULL DEFAULT '{}'::jsonb,
  usage jsonb NOT NULL DEFAULT '{}'::jsonb,
  coverage jsonb NOT NULL DEFAULT '[]'::jsonb,
  upstream_ref text,
  model_ref text,
  prompt_version text NOT NULL,
  checkpoint_ref text,
  attempt integer NOT NULL DEFAULT 0,
  stop_reason text,
  next_event_seq bigint NOT NULL DEFAULT 0,
  parent_run_id uuid,
  updated_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  CHECK (status IN ('queued', 'running', 'awaiting_input', 'verifying', 'completed', 'partial', 'failed', 'cancelling', 'cancelled', 'recovery_required')),
  CHECK (runtime_mode IN ('replay', 'deerflow'))
);

CREATE TABLE run_event (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  run_id uuid NOT NULL,
  seq bigint NOT NULL CHECK(seq>0),
  schema_version text NOT NULL DEFAULT '1.0',
  type text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  UNIQUE(workspace_id,run_id,seq)
);

CREATE TABLE tool_call (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  run_id uuid NOT NULL,
  call_key text NOT NULL,
  tool text NOT NULL,
  state text NOT NULL,
  arguments_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  evidence_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  error_code text,
  duration_ms bigint CHECK(duration_ms>=0),
  usage jsonb NOT NULL DEFAULT '{}'::jsonb,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  CHECK (state IN ('started', 'completed', 'failed', 'cancelled')),
  UNIQUE(workspace_id,run_id,call_key)
);

CREATE TABLE report (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  run_id uuid NOT NULL,
  created_by uuid NOT NULL REFERENCES app_user(id),
  title text NOT NULL,
  state text NOT NULL DEFAULT 'draft',
  current_version_id uuid,
  published_version_id uuid,
  retracted_at timestamptz,
  retraction_reason text,
  updated_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  CHECK (state IN ('draft', 'in_review', 'changes_requested', 'approved', 'published', 'retracted')),
  UNIQUE(workspace_id,run_id)
);

CREATE TABLE report_version (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  report_id uuid NOT NULL,
  version_no integer NOT NULL CHECK(version_no>0),
  created_by uuid NOT NULL REFERENCES app_user(id),
  content_json jsonb NOT NULL,
  content_hash char(64) NOT NULL,
  runtime_mode text NOT NULL,
  edit_note text NOT NULL DEFAULT 'initial',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  CHECK (runtime_mode IN ('replay', 'deerflow')),
  UNIQUE(workspace_id,report_id,version_no)
);

CREATE TABLE claim (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  report_version_id uuid NOT NULL,
  claim_key text NOT NULL,
  statement text NOT NULL,
  category text NOT NULL,
  qualifiers jsonb NOT NULL DEFAULT '{}'::jsonb,
  verification_status text NOT NULL,
  numeric_check text NOT NULL,
  verification_meta jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  CHECK (category IN ('fact', 'hypothesis', 'gap')),
  CHECK (verification_status IN ('unverified', 'supported', 'conflicted', 'insufficient')),
  CHECK (numeric_check IN ('passed', 'failed', 'not_applicable', 'manual_check_required')),
  UNIQUE(workspace_id,report_version_id,claim_key)
);

CREATE TABLE claim_evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  claim_id uuid NOT NULL,
  evidence_id uuid NOT NULL,
  relation text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  CHECK (relation IN ('supports', 'contradicts', 'context')),
  UNIQUE(workspace_id,claim_id,evidence_id,relation)
);

CREATE TABLE review (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  report_id uuid NOT NULL,
  version_id uuid NOT NULL,
  reviewer_id uuid NOT NULL REFERENCES app_user(id),
  content_hash char(64) NOT NULL,
  decision text NOT NULL,
  note text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  CHECK (decision IN ('approve', 'request_changes'))
);

CREATE TABLE subscription (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  owner_id uuid NOT NULL REFERENCES app_user(id),
  name text NOT NULL,
  drug_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  source_allowlist jsonb NOT NULL DEFAULT '[]'::jsonb,
  schedule jsonb NOT NULL,
  channels jsonb NOT NULL DEFAULT '[]'::jsonb,
  enabled boolean NOT NULL DEFAULT true,
  revision integer NOT NULL DEFAULT 1 CHECK(revision>0),
  next_run_at timestamptz,
  last_outcome text,
  updated_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id)
);

CREATE TABLE schedule_occurrence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  subscription_id uuid NOT NULL,
  scheduled_at timestamptz NOT NULL,
  config_snapshot jsonb NOT NULL,
  state text NOT NULL DEFAULT 'queued',
  run_id uuid,
  trigger_kind text NOT NULL DEFAULT 'scheduled',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  CHECK (state IN ('queued', 'running', 'generated', 'no_change', 'partial', 'failed', 'cancelled')),
  UNIQUE(workspace_id,subscription_id,scheduled_at)
);

CREATE TABLE subscription_cursor (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  subscription_id uuid NOT NULL,
  event_id uuid NOT NULL,
  channel text NOT NULL,
  last_accepted_revision_id uuid,
  updated_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  CHECK (channel IN ('in_app', 'email')),
  UNIQUE(workspace_id,subscription_id,event_id,channel)
);

CREATE TABLE delivery (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  report_version_id uuid NOT NULL,
  subscription_id uuid,
  recipient_user_id uuid NOT NULL REFERENCES app_user(id),
  channel text NOT NULL,
  state text NOT NULL DEFAULT 'queued',
  idempotency_key text NOT NULL,
  rendered_payload jsonb NOT NULL,
  covered_event_revisions jsonb NOT NULL DEFAULT '[]'::jsonb,
  attempt_count integer NOT NULL DEFAULT 0,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  owner_token uuid,
  lease_expires_at timestamptz,
  accepted_at timestamptz,
  read_at timestamptz,
  error_code text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  CHECK (channel IN ('in_app', 'email')),
  CHECK (state IN ('queued', 'sending', 'accepted', 'unknown', 'failed', 'cancelled')),
  UNIQUE(workspace_id,report_version_id,recipient_user_id,channel),
  UNIQUE(workspace_id,idempotency_key)
);

CREATE TABLE delivery_attempt (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  delivery_id uuid NOT NULL,
  attempt_no integer NOT NULL CHECK(attempt_no>0),
  outcome text NOT NULL,
  provider_message_id text,
  error_code text,
  started_at timestamptz NOT NULL,
  finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  CHECK (outcome IN ('started', 'accepted', 'failed', 'unknown')),
  UNIQUE(workspace_id,delivery_id,attempt_no)
);

CREATE TABLE artifact (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  run_id uuid,
  report_version_id uuid,
  object_key text NOT NULL,
  content_type text NOT NULL,
  byte_size bigint NOT NULL CHECK(byte_size>=0),
  content_hash char(64) NOT NULL,
  is_demo boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  UNIQUE(workspace_id,object_key)
);

CREATE TABLE audit_log (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  actor_id uuid REFERENCES app_user(id),
  action text NOT NULL,
  target_type text NOT NULL,
  target_id uuid,
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  request_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id)
);

CREATE TABLE idempotency_record (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  actor_id uuid NOT NULL REFERENCES app_user(id),
  operation text NOT NULL,
  key text NOT NULL,
  request_hash char(64) NOT NULL,
  response_status integer,
  response_body jsonb,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, id),
  UNIQUE(workspace_id,actor_id,operation,key)
);

ALTER TABLE drug_alias ADD FOREIGN KEY (workspace_id, drug_id) REFERENCES drug(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE drug_alias ADD FOREIGN KEY (workspace_id, evidence_id) REFERENCES evidence(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE source_snapshot ADD FOREIGN KEY (workspace_id, record_id) REFERENCES source_record(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE source_observation ADD FOREIGN KEY (workspace_id, record_id) REFERENCES source_record(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE source_observation ADD FOREIGN KEY (workspace_id, snapshot_id) REFERENCES source_snapshot(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE source_record ADD FOREIGN KEY (workspace_id, current_snapshot_id) REFERENCES source_snapshot(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE source_record ADD FOREIGN KEY (workspace_id, current_observation_id) REFERENCES source_observation(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE entity_link ADD FOREIGN KEY (workspace_id, record_id) REFERENCES source_record(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE entity_link ADD FOREIGN KEY (workspace_id, drug_id) REFERENCES drug(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE entity_link ADD FOREIGN KEY (workspace_id, evidence_id) REFERENCES evidence(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE evidence ADD FOREIGN KEY (workspace_id, snapshot_id) REFERENCES source_snapshot(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE intelligence_event ADD FOREIGN KEY (workspace_id, record_id) REFERENCES source_record(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE intelligence_event ADD FOREIGN KEY (workspace_id, latest_revision_id) REFERENCES event_revision(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE event_revision ADD FOREIGN KEY (workspace_id, event_id) REFERENCES intelligence_event(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE event_revision ADD FOREIGN KEY (workspace_id, before_observation_id) REFERENCES source_observation(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE event_revision ADD FOREIGN KEY (workspace_id, after_observation_id) REFERENCES source_observation(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE research_run ADD FOREIGN KEY (workspace_id, job_id) REFERENCES job(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE research_run ADD FOREIGN KEY (workspace_id, parent_run_id) REFERENCES research_run(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE run_event ADD FOREIGN KEY (workspace_id, run_id) REFERENCES research_run(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE tool_call ADD FOREIGN KEY (workspace_id, run_id) REFERENCES research_run(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE report ADD FOREIGN KEY (workspace_id, run_id) REFERENCES research_run(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE report ADD FOREIGN KEY (workspace_id, current_version_id) REFERENCES report_version(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE report ADD FOREIGN KEY (workspace_id, published_version_id) REFERENCES report_version(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE report_version ADD FOREIGN KEY (workspace_id, report_id) REFERENCES report(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE claim ADD FOREIGN KEY (workspace_id, report_version_id) REFERENCES report_version(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE claim_evidence ADD FOREIGN KEY (workspace_id, claim_id) REFERENCES claim(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE claim_evidence ADD FOREIGN KEY (workspace_id, evidence_id) REFERENCES evidence(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE review ADD FOREIGN KEY (workspace_id, report_id) REFERENCES report(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE review ADD FOREIGN KEY (workspace_id, version_id) REFERENCES report_version(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE schedule_occurrence ADD FOREIGN KEY (workspace_id, subscription_id) REFERENCES subscription(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE schedule_occurrence ADD FOREIGN KEY (workspace_id, run_id) REFERENCES research_run(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE subscription_cursor ADD FOREIGN KEY (workspace_id, subscription_id) REFERENCES subscription(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE subscription_cursor ADD FOREIGN KEY (workspace_id, event_id) REFERENCES intelligence_event(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE subscription_cursor ADD FOREIGN KEY (workspace_id, last_accepted_revision_id) REFERENCES event_revision(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE delivery ADD FOREIGN KEY (workspace_id, report_version_id) REFERENCES report_version(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE delivery ADD FOREIGN KEY (workspace_id, subscription_id) REFERENCES subscription(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE delivery_attempt ADD FOREIGN KEY (workspace_id, delivery_id) REFERENCES delivery(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE artifact ADD FOREIGN KEY (workspace_id, run_id) REFERENCES research_run(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE artifact ADD FOREIGN KEY (workspace_id, report_version_id) REFERENCES report_version(workspace_id, id) DEFERRABLE INITIALLY IMMEDIATE;

CREATE INDEX idx_alias_lookup ON drug_alias (workspace_id,normalized_alias);

CREATE INDEX idx_records_list ON source_record (workspace_id,kind,updated_at DESC,id);

CREATE INDEX idx_snapshot_record ON source_snapshot (workspace_id,record_id,first_observed_at DESC);

CREATE INDEX idx_observation_record ON source_observation (workspace_id,record_id,observation_seq DESC);

CREATE INDEX idx_event_recent ON intelligence_event (workspace_id,updated_at DESC,id);

CREATE INDEX idx_event_revision ON event_revision (workspace_id,event_id,observed_at DESC);

CREATE INDEX idx_job_ready ON job (state,available_at);

CREATE INDEX idx_run_creator ON research_run (workspace_id,created_by,created_at DESC,id);

CREATE INDEX idx_report_state ON report (workspace_id,state,updated_at DESC,id);

CREATE INDEX idx_delivery_ready ON delivery (state,next_attempt_at);

CREATE INDEX idx_delivery_inbox ON delivery (workspace_id,recipient_user_id,created_at DESC,id);

CREATE INDEX idx_subscription_due ON subscription (enabled,next_run_at);

-- Application service users must not mutate immutable content. Special retention/legal
-- removal is an explicit administrative migration, not a public API bypass.
CREATE FUNCTION reject_immutable_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'immutable table % cannot be updated or deleted', TG_TABLE_NAME;
END;
$$;

CREATE TRIGGER immutable_source_snapshot BEFORE UPDATE OR DELETE ON source_snapshot FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

CREATE TRIGGER immutable_source_observation BEFORE UPDATE OR DELETE ON source_observation FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON evidence FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

CREATE TRIGGER immutable_event_revision BEFORE UPDATE OR DELETE ON event_revision FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

CREATE TRIGGER immutable_report_version BEFORE UPDATE OR DELETE ON report_version FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

CREATE TRIGGER immutable_claim BEFORE UPDATE OR DELETE ON claim FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

CREATE TRIGGER immutable_claim_evidence BEFORE UPDATE OR DELETE ON claim_evidence FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

CREATE TRIGGER immutable_review BEFORE UPDATE OR DELETE ON review FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

CREATE TRIGGER immutable_run_event BEFORE UPDATE OR DELETE ON run_event FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

CREATE TRIGGER immutable_audit_log BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

-- RLS and database-role provisioning are intentionally not asserted here.
-- Add and test scoped repository access, optional RLS, and role grants in application migrations.

-- Separate notices preserve the original published report content.
CREATE TABLE report_notice (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 workspace_id uuid NOT NULL REFERENCES workspace(id),
 report_id uuid NOT NULL, version_id uuid NOT NULL, event_revision_id uuid,
 type text NOT NULL CHECK(type IN ('source_updated','report_retracted')),
 message text NOT NULL, notice_key text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(workspace_id,id), UNIQUE(workspace_id,notice_key),
 FOREIGN KEY(workspace_id,report_id) REFERENCES report(workspace_id,id),
 FOREIGN KEY(workspace_id,version_id) REFERENCES report_version(workspace_id,id),
 FOREIGN KEY(workspace_id,event_revision_id) REFERENCES event_revision(workspace_id,id)
);
CREATE INDEX idx_report_notice_version ON report_notice(workspace_id,version_id,created_at DESC);
CREATE TRIGGER immutable_report_notice BEFORE UPDATE OR DELETE ON report_notice
 FOR EACH ROW EXECUTE FUNCTION reject_immutable_change();

COMMIT;
