-- AURORA local state schema.
-- v2.1 FINAL canonical tables (Sección 8) PLUS the original Sprint 1 tables,
-- kept additively so the already-deployed server keeps working.
-- New databases get every column; existing databases are upgraded by the
-- idempotent ALTER TABLE migrations in db.migrate_db().

-- ---------------------------------------------------------------------------
-- v2.1 FINAL core tables (Sección 8)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS projects (
  project_id TEXT PRIMARY KEY,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  operator_intent TEXT NOT NULL,
  mode TEXT NOT NULL CHECK(mode IN ('image','video_simple','video_multishot')),
  output_type TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  current_phase TEXT,
  domain_session_lock_json TEXT,
  required_higgsfield_element_ids TEXT
);

CREATE TABLE IF NOT EXISTS briefs (
  brief_id TEXT PRIMARY KEY,
  project_id TEXT REFERENCES projects(project_id),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  brief_type TEXT CHECK(brief_type IN ('image','video','multishot') OR brief_type IS NULL),
  brief_json TEXT NOT NULL,
  validated_at TIMESTAMP,
  gate_result_json TEXT
);

CREATE TABLE IF NOT EXISTS benchmark_refs (
  benchmark_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  url_or_path TEXT NOT NULL,
  visual_traits_json TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS route_registry (
  route_id TEXT PRIMARY KEY,
  project_id TEXT REFERENCES projects(project_id),
  feature_name TEXT NOT NULL,
  route_type TEXT NOT NULL CHECK(route_type IN ('mcp_callable','ui_only','hybrid','not_verified','outside_aurora')),
  verification_source TEXT,
  verified_at TIMESTAMP,
  confidence REAL DEFAULT 0,
  route_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS capability_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  refresh_scope TEXT NOT NULL,
  source TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  diff_from_previous_json TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
  audit_id TEXT PRIMARY KEY,
  project_id TEXT REFERENCES projects(project_id),
  higgsfield_job_id TEXT,
  higgsfield_element_id TEXT,
  criterion TEXT NOT NULL,
  verdict TEXT NOT NULL CHECK(verdict IN ('pass','fail','marginal')),
  notes TEXT,
  audited_by TEXT NOT NULL CHECK(audited_by IN ('aurora','operator')),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS quality_scores (
  score_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  higgsfield_job_id TEXT,
  higgsfield_element_id TEXT,
  score_type TEXT NOT NULL CHECK(score_type IN ('image','video','multishot','biomechanics','prompt','production_probability')),
  score_json TEXT NOT NULL,
  total_score INTEGER NOT NULL,
  hard_fail_reason TEXT,
  scored_by TEXT NOT NULL CHECK(scored_by IN ('aurora','operator')),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS execution_packs (
  pack_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  version INTEGER NOT NULL DEFAULT 1,
  anchors_approved_count INTEGER DEFAULT 0,
  anchors_required_count INTEGER DEFAULT 0,
  success_criteria_json TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bypass_log (
  bypass_id TEXT PRIMARY KEY,
  timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  project_id TEXT,
  operator_turn_text TEXT NOT NULL,
  component_bypassed TEXT NOT NULL,
  reason TEXT NOT NULL,
  scope TEXT NOT NULL CHECK(scope IN ('current_turn','persist','all_session')),
  related_job_id TEXT,
  job_outcome TEXT
);

CREATE TABLE IF NOT EXISTS active_bypasses (
  component TEXT PRIMARY KEY,
  project_id TEXT,
  scope TEXT NOT NULL CHECK(scope IN ('persist','all_session')),
  reason TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  revoked_at TIMESTAMP
);

-- ---------------------------------------------------------------------------
-- Sprint 1 operational tables (kept for backward compatibility)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS shots (
  shot_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  shot_number INTEGER NOT NULL,
  duration_seconds REAL NOT NULL,
  shot_type TEXT NOT NULL,
  function TEXT,
  camera_movement TEXT,
  speed_ramp TEXT,
  biomechanical_motion_plan_json TEXT,
  anchor_strategy_json TEXT,
  prompt_creative TEXT,
  prompt_technical_per_model_json TEXT,
  prompt_biomechanical TEXT,
  prompt_continuity TEXT,
  negative_constraints_json TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS soul_ids (
  soul_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  platform TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  identity_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS elements (
  element_id TEXT PRIMARY KEY,
  project_id TEXT REFERENCES projects(project_id),
  element_type TEXT NOT NULL CHECK(element_type IN ('character','product','prop','location','style','frame','environment','video_ref')),
  name TEXT NOT NULL,
  sheet_json TEXT NOT NULL,
  reference_image_path TEXT,
  higgsfield_element_id TEXT,
  audit_status TEXT,
  quality_score INTEGER,
  usage_role TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS reference_packs (
  pack_id TEXT PRIMARY KEY,
  project_id TEXT REFERENCES projects(project_id),
  name TEXT NOT NULL,
  element_ids_json TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  project_id TEXT REFERENCES projects(project_id),
  shot_id TEXT REFERENCES shots(shot_id),
  platform TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_sent TEXT NOT NULL,
  payload_json TEXT,
  status TEXT NOT NULL CHECK(status IN ('pending','success','failure')),
  output_uri TEXT,
  outcome_notes TEXT,
  credits_estimated INTEGER,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS workflows_cache (
  workflow_id TEXT PRIMARY KEY,
  domain TEXT NOT NULL,
  sub_domain TEXT NOT NULL,
  style TEXT NOT NULL,
  yaml_content TEXT NOT NULL,
  sources_json TEXT NOT NULL,
  cached_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP NOT NULL
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_briefs_project ON briefs(project_id);
CREATE INDEX IF NOT EXISTS idx_benchmark_project ON benchmark_refs(project_id);
CREATE INDEX IF NOT EXISTS idx_route_project ON route_registry(project_id);
CREATE INDEX IF NOT EXISTS idx_audit_project ON audit_log(project_id);
CREATE INDEX IF NOT EXISTS idx_scores_project ON quality_scores(project_id);
CREATE INDEX IF NOT EXISTS idx_packs_project ON execution_packs(project_id);
CREATE INDEX IF NOT EXISTS idx_shots_project ON shots(project_id);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id);
CREATE INDEX IF NOT EXISTS idx_bypass_project ON bypass_log(project_id);
CREATE INDEX IF NOT EXISTS idx_workflows_domain ON workflows_cache(domain, sub_domain, style);
