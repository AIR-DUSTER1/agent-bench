// 与后端 api/ 路由的响应结构一一对应（改动后端响应时同步这里）
export interface AgentVersion {
  id: number
  version: string
  config: Record<string, unknown>
  note: string
  created_at: string
}

export interface Agent {
  id: number
  name: string
  description: string
  type: string
  versions: AgentVersion[]
}

export interface TestResult {
  output: string
  error: string
  intermediate: unknown[]
  latency_ms: number
  token_usage: Record<string, number>
}

export interface EvalCase {
  id?: number
  seq?: number
  input: string
  expected_output?: string
  reference_context?: string
  tools_spec?: Record<string, unknown>
  difficulty?: string
  tags?: Record<string, string>
  meta?: Record<string, unknown>
}

export interface DatasetVersion {
  id: number
  version: string
  note?: string
  case_count: number
  quality_summary?: { blockers?: number; warnings?: number; by_rule?: Record<string, number> }
  created_at: string
  is_draft?: boolean
  cases?: EvalCase[]
}

export interface DatasetListItem {
  id: number
  name: string
  description: string
  target_types: string
  draft_count: number
  versions: Pick<DatasetVersion, 'id' | 'version' | 'case_count' | 'created_at'>[]
}

export interface DatasetDetail {
  id: number
  name: string
  description: string
  target_types: string
  draft: DatasetVersion
  versions: DatasetVersion[]
}

export interface QualityIssue {
  level: string
  rule: string
  seq: number | null
  detail: string
}

export interface QualitySummary {
  blockers: number
  warnings: number
  issues: QualityIssue[]
  by_rule?: Record<string, number>
}

export interface ImportPreflight {
  confirm_required: boolean
  quality: QualitySummary
  to_import: number
  draft_existing: number
}

export interface ImportResult {
  imported: number
  quality: QualitySummary
}

export interface PublishResult {
  id: number
  version: string
  note?: string
  case_count: number
}

export interface ExportOut {
  dataset: string
  version: string
  cases: EvalCase[]
}

export interface RunSide {
  agent_version_id: number
  version: string
  agent_name: string
  agent_type: string
}

export interface EvalRun {
  id: number
  name: string
  mode: string
  status: string
  sides: RunSide[]
  dataset_version_id: number
  judge_model: string
  judge_mode: string
  dimension_codes: string[]
  concurrency: number
  progress: number
  total_cases: number
  error: string
  started_at: string | null
  finished_at: string | null
  created_at: string
  report_id?: number
}

export interface Health {
  status: string
  app: string
  llm_configured: boolean
  llm_model: string
  judge_model: string
  langfuse_enabled: boolean
  trace_mode: string
}

export interface Settings {
  llm_base_url: string
  llm_model: string
  llm_api_key_masked: string
  judge_base_url: string
  judge_model: string
  judge_api_key_masked: string
  exec_concurrency: number
  judge_concurrency: number
  pass_threshold: number
  langfuse_host: string
  langfuse_enabled: boolean
  database_url_masked: string
}

export interface Dimension {
  id: number
  code: string
  name: string
  weight: number
  is_builtin: boolean
  enabled: boolean
  rubric: string
}

export interface TagItem {
  id: number
  value: string
  label: string
  enabled: boolean
}

export interface QualityReportRow {
  id: number
  dataset_id: number
  triggered_by: string
  blockers: number
  warnings: number
  issues: QualityIssue[]
  created_at: string
}

// ---------- token 统计（口径与后端 metrics.normalize_usage 对齐） ----------

export interface NormalizedUsage {
  input_tokens: number
  output_tokens: number
  total_tokens: number
  source: 'api' | 'approx_chars' | 'none'
  input_chars?: number
  output_chars?: number
}

export interface UsageStat {
  input_tokens: number
  output_tokens: number
  total_tokens: number
  calls: number
  api_calls: number
  approx_calls: number
  none_calls: number
}

export interface TokenRow {
  case_result_id: number
  seq: number
  status: string
  agent_name: string
  agent_version: string
  usage: NormalizedUsage
  judge_usage: NormalizedUsage
}

export interface RunTokens {
  run_id: number
  rows: TokenRow[]
  agent_total: UsageStat
  judge_total: UsageStat
}

export interface StatsEntry {
  key?: string
  run_id?: number
  name?: string
  status?: string
  created_at?: string
  agent: UsageStat
  judge: UsageStat
}

export interface TokenStats {
  total: { agent: UsageStat; judge: UsageStat }
  by_run: StatsEntry[]
  by_agent: StatsEntry[]
  by_date: StatsEntry[]
}
