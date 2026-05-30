-- AURORA local state — Sprint 1 schema
CREATE TABLE IF NOT EXISTS projects (
  project_id TEXT PRIMARY KEY,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  operator_intent TEXT NOT NULL,
  mode TEXT NOT NULL CHECK(mode IN ('image', 'video_simple', 'video_multishot')),
  status TEXT NOT NULL DEFAULT 'open'
);
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
  element_type TEXT NOT NULL CHECK(element_type IN ('character','product','prop','location','style','frame')),
  name TEXT NOT NULL,
  sheet_json TEXT NOT NULL,
  reference_image_path TEXT,
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
CREATE TABLE IF NOT EXISTS bypass_log (
  bypass_id TEXT PRIMARY KEY,
  timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  project_id TEXT,
  operator_turn_text TEXT NOT NULL,
  component_bypassed TEXT NOT NULL,
  reason TEXT NOT NULL,
  scope TEXT NOT NULL CHECK(scope IN ('current_turn','persist','all_session')),
  related_job_id TEXT REFERENCES jobs(job_id),
  job_outcome TEXT CHECK(job_outcome IN ('success','failure','pending') OR job_outcome IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_shots_project ON shots(project_id);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id);
CREATE INDEX IF NOT EXISTS idx_bypass_project ON bypass_log(project_id);
CREATE INDEX IF NOT EXISTS idx_workflows_domain ON workflows_cache(domain, sub_domain, style);
