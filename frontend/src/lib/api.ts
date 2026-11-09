import type {
  EligibilityResponse,
  EvalReport,
  ProviderStatus,
  SchemeDetail,
  SchemeList,
  ChecklistItem,
  UserProfile,
} from './types'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = body.detail ?? detail
    } catch {
      // Non-JSON error bodies keep the status text.
    }
    throw new ApiError(response.status, String(detail))
  }
  return (await response.json()) as T
}

export interface SchemeQuery {
  q?: string
  state?: string
  category?: string
  page?: number
  pageSize?: number
}

export function listSchemes(query: SchemeQuery = {}): Promise<SchemeList> {
  const params = new URLSearchParams()
  if (query.q) params.set('q', query.q)
  if (query.state) params.set('state', query.state)
  if (query.category) params.set('category', query.category)
  params.set('page', String(query.page ?? 1))
  params.set('page_size', String(query.pageSize ?? 48))
  return request<SchemeList>(`/api/schemes?${params}`)
}

export function getScheme(id: string): Promise<SchemeDetail> {
  return request<SchemeDetail>(`/api/schemes/${encodeURIComponent(id)}`)
}

export function getChecklist(
  id: string,
): Promise<{ scheme_id: string; name: string; items: ChecklistItem[] }> {
  return request(`/api/schemes/${encodeURIComponent(id)}/checklist`)
}

export function checkEligibility(
  profile: UserProfile,
  schemeIds?: string[],
  askedFields: string[] = [],
): Promise<EligibilityResponse> {
  return request<EligibilityResponse>('/api/eligibility', {
    method: 'POST',
    body: JSON.stringify({ profile, scheme_ids: schemeIds ?? null, asked_fields: askedFields }),
  })
}

export function getProviders(): Promise<{ providers: ProviderStatus[]; checked_at: string }> {
  return request('/api/health/providers')
}

export function getLatestEval(): Promise<EvalReport> {
  return request<EvalReport>('/api/eval/latest')
}

export function getHealth(): Promise<{ schemes: number; chunks: number }> {
  return request('/api/health')
}
