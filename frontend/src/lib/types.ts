export type Language = 'en' | 'hi'

export interface UserProfile {
  age?: number | null
  gender?: string | null
  state?: string | null
  annual_family_income?: number | null
  social_category?: string | null
  occupation?: string | null
  education_level?: string | null
  disability?: boolean | null
  residence?: string | null
}

export type ProfileField = keyof UserProfile

export interface CategoryLabel {
  en: string
  hi: string
}

export interface SchemeSummary {
  scheme_id: string
  name: string
  names: Record<string, string>
  ministry: string | null
  state: string
  category: string
  category_label: CategoryLabel
  tags: string[]
  summary: string
  languages: string[]
  is_sample: boolean
  has_rules: boolean
  rules_reviewed: boolean
  last_seen: string
}

export interface SchemeList {
  items: SchemeSummary[]
  total: number
  page: number
  page_size: number
  facets: { states: string[]; categories: { key: string; label: CategoryLabel }[] }
}

export interface SchemeSectionView {
  name: string
  label: string
  heading: string
  text: string
  language: string
  source_url: string
  page: number | null
  chunk_ids: string[]
}

export interface ChecklistItem {
  id: string
  text: string
  chunk_id: string
  source_url: string
  page: number | null
  language: string
}

export interface RuleValue<T> {
  value: T | null
  chunk_id: string | null
}

export interface EligibilityRules {
  min_age: RuleValue<number>
  max_age: RuleValue<number>
  genders: RuleValue<string[]>
  states: RuleValue<string[]>
  max_annual_family_income: RuleValue<number>
  social_categories: RuleValue<string[]>
  occupations: RuleValue<string[]>
  education_levels: RuleValue<string[]>
  disability_required: RuleValue<boolean>
  residence: RuleValue<string>
  other_conditions: { text: string; chunk_id: string | null }[]
}

export interface RulesRecord {
  scheme_id: string
  scheme_name: string
  rules: EligibilityRules
  needs_review: boolean
  reviewed_at: string | null
}

export interface RuleSource {
  chunk_id: string
  text: string
  section: string
  source_url: string
  page: number | null
}

export interface SchemeDetail extends SchemeSummary {
  sections: SchemeSectionView[]
  source_urls: string[]
  rules: RulesRecord | null
  rules_usable: boolean
  rule_sources: Record<string, RuleSource>
  checklist: ChecklistItem[]
}

export type CriterionStatus = 'met' | 'unmet' | 'unknown'
export type Verdict = 'eligible' | 'partial' | 'ineligible' | 'unknown'

export interface Criterion {
  field: string
  label: string
  status: CriterionStatus
  expected: string
  expected_values: (string | number | boolean)[]
  actual: string | null
  chunk_id: string | null
  resolvable: boolean
  source?: RuleSource | null
}

export interface SchemeEligibility {
  scheme_id: string
  scheme_name: string
  verdict: Verdict
  criteria: Criterion[]
  met: number
  total: number
  score: number
  missing_fields: string[]
  rules_reviewed: boolean
  scheme?: SchemeSummary | null
}

export interface QuickReply {
  label: string
  label_hi: string
  value: string | number | boolean
}

export interface ClarifyQuestion {
  field: ProfileField
  question: string
  question_hi: string
  input: 'choice' | 'number'
  options: QuickReply[]
  resolves: number
  affects: number
}

export interface EligibilityResponse {
  results: SchemeEligibility[]
  counts: Record<Verdict, number>
  pending_review: string[]
  question: ClarifyQuestion | null
}

export interface Citation {
  n: number
  chunk_id: string
  scheme_id: string
  scheme_name: string
  section: string
  section_label: string
  heading: string
  source_url: string
  page: number | null
  text: string
  language: string
  is_sample: boolean
  cited: boolean
}

export interface ProviderInfo {
  name: string
  label: string
  model: string
  offline: boolean
  cached: boolean
}

export interface ProviderStatus {
  name: string
  label: string
  model: string
  status: 'ok' | 'cooldown' | 'disabled' | 'budget_exhausted'
  detail: string
  cooldown_until: string | null
  cooldown_seconds: number
  offline: boolean
  trains_on_free_tier_data: boolean
  limits: { rpm: number | null; rpd: number | null; tpm: number | null; tpd: number | null }
  usage_today: { requests: number; tokens: number }
}

export type StageName =
  'understanding' | 'searching' | 'fusing' | 'reranking' | 'checking_eligibility' | 'writing'

export interface StageState {
  status: 'pending' | 'active' | 'done' | 'skipped'
  ms?: number
}

export interface EvalRun {
  name: string
  label: string
  status: 'ok' | 'skipped'
  reason?: string
  config: Record<string, unknown>
  questions: number
  retrieval: Record<string, number>
}

export interface EvalGeneration {
  status: 'ok' | 'skipped'
  reason?: string
  faithfulness?: number | null
  citation_precision?: number | null
  abstention_accuracy?: number | null
  latency?: { p50_ms: number; p95_ms: number; cached_share: number }
}

export interface EvalReport {
  created_at: string
  corpus: string
  golden_file: string
  questions: number
  answerable: number
  unanswerable: number
  chunks?: number
  runs: EvalRun[]
  abstention: {
    score: string
    current_threshold: number
    accuracy_at_current: number | null
    recommended_threshold: number | null
    sweep: { threshold: number; accuracy: number; balanced: number }[]
  } | null
  generation: EvalGeneration | null
  notes: string[]
  file?: string
  example?: boolean
}
