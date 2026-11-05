// Thin client for the Deliverable Guard API.

export type Role = 'admin' | 'handler' | 'reviewer' | 'manager' | 'legal'
export interface User { id: number; username: string; display_name: string; role: Role; clearance: number; active: boolean }

export interface Project {
  id: number; name: string; scenario: string; classification: number; classification_label: string
  deid_enabled: boolean; retain_until: string; created_at: string; documents: number
  last_check: CheckSummary | null
  findings: Record<'open' | 'confirmed' | 'dismissed' | 'disputed', number>
  doc_types: string[]
  pending_by_kind: Record<'contradiction' | 'omission' | 'outdated', number>
  pending_by_severity: Record<'high' | 'medium' | 'low', number>
  approval: { id: number; status: ApprovalStatus } | null
}

export type ApprovalStatus = 'in_progress' | 'approved' | 'rejected' | 'withdrawn' | 'invalidated'
export interface WfCondition { type: 'always' | 'amount_gte' | 'has_doc_type' | 'has_high'; value?: number | string }
export interface WfNode { name: string; assignee_type: 'role' | 'users'; role: string; users: number[]; condition: WfCondition }
export interface ResolvedNode extends WfNode { skipped: boolean; reason: string; assignee_label: string }
export interface WfTemplate { id: number; name: string; scenario: string; nodes: WfNode[]; active: boolean }
export interface Gate { key: string; ok: boolean; label: string; detail: string }
export interface ApprovalStepT { node_index: number; node_name: string; action: 'approve' | 'reject' | 'comment'; comment: string; user: string; role: string; at: string; signature: string }
export interface Approval {
  id: number; project_id: number; project_name?: string; template_name: string; note: string
  status: ApprovalStatus; status_label: string; status_reason: string; nodes: ResolvedNode[]; current: number
  snapshot: { documents: { filename: string; doc_type: string; version: string; latest: boolean; sha256: string }[]; total_amount: number | null; findings: { confirmed: number; dismissed: number } }
  snapshot_hash: string; submitted_by: string; submitted_at: string; completed_at: string | null
  can_act: boolean; can_withdraw: boolean; steps: ApprovalStepT[]
}

export interface CheckSummary {
  run_id: string; at: string; llm: boolean; documents: number; facts: number; findings: number
  by_kind: Record<string, number>; seconds: number; llm_calls: number
}

export interface Doc {
  id: number; filename: string; fmt: string; size: number; doc_type: string; doc_type_label: string
  version_label: string; version_group: string; is_latest: boolean; doc_date: string | null
  pages: number; ocr_pages: number; warnings: string[]; status: string; uploaded_at: string; sha256: string
}

export interface Segment { id: number; page: number | null; locator: string; text: string; ocr: boolean; raw_text: string | null }

export interface Evidence {
  doc_id: number; filename: string; doc_type: string; version: string; page: number | null
  locator: string; quote: string; text: string; value: string; note: string
}

export interface Review { user: string; role: string; decision: 'confirm' | 'dismiss'; final: boolean; comment: string; at: string }

export interface Finding {
  id: number; kind: 'contradiction' | 'omission' | 'outdated'; severity: 'high' | 'medium' | 'low'
  field: string; item: string; title: string; detail: string; evidence: Evidence[]; detector: string
  status: 'open' | 'confirmed' | 'dismissed' | 'disputed'; created_at: string; reviews: Review[]
}

export interface FactCell { value: string; norm: string; quote: string; page: number | null; locator: string; source: string; latest: boolean }
export interface FactRow {
  field: string; label: string; item: string; consistent: boolean
  reference: { doc_id: number; value: string } | null
  values: Record<string, FactCell[]>
}

export interface Health { ok: boolean; llm: boolean; open_login?: boolean; llm_model: string; classifications: Record<string, string>; doc_types: Record<string, string> }

const TOKEN_KEY = 'dg_token'

export function getToken(): string | null {
  try { return sessionStorage.getItem(TOKEN_KEY) } catch { return null }
}
export function setToken(t: string | null) {
  try { t ? sessionStorage.setItem(TOKEN_KEY, t) : sessionStorage.removeItem(TOKEN_KEY) } catch { /* storage blocked */ }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  let payload: BodyInit | undefined
  if (body instanceof FormData) payload = body
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body) }
  const r = await fetch(path, { method, headers, body: payload })
  if (r.status === 401 && path !== '/api/auth/login') {
    setToken(null)
    window.dispatchEvent(new Event('dg:logout'))
  }
  if (!r.ok) {
    let msg = r.statusText
    try { const j = await r.json(); msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail) } catch { /* not json */ }
    throw new ApiError(r.status, msg)
  }
  return r.headers.get('content-type')?.includes('json') ? r.json() : (r.blob() as Promise<T>)
}

export const api = {
  login: (username: string, password: string) => req<{ token: string; user: User }>('POST', '/api/auth/login', { username, password }),
  me: () => req<User>('GET', '/api/me'),
  health: () => req<Health>('GET', '/api/health'),
  users: () => req<User[]>('GET', '/api/users'),
  createUser: (u: Partial<User> & { password: string }) => req<User>('POST', '/api/users', u),
  updateUser: (id: number, u: Partial<User> & { password?: string }) => req<User>('PATCH', `/api/users/${id}`, u),
  projects: () => req<Project[]>('GET', '/api/projects'),
  project: (id: number) => req<Project>('GET', `/api/projects/${id}`),
  createProject: (p: { name: string; scenario: string; classification: number; retention_days: number; deid_enabled: boolean }) =>
    req<Project>('POST', '/api/projects', p),
  patchProject: (id: number, p: { name?: string; retention_days?: number; classification?: number }) => req<Project>('PATCH', `/api/projects/${id}`, p),
  deleteProject: (id: number) => req<{ ok: boolean }>('DELETE', `/api/projects/${id}`),
  docs: (pid: number) => req<Doc[]>('GET', `/api/projects/${pid}/documents`),
  upload: (pid: number, files: File[]) => {
    const fd = new FormData()
    files.forEach(f => fd.append('files', f))
    return req<{ uploaded: Doc[]; errors: { filename: string; error: string }[] }>('POST', `/api/projects/${pid}/documents`, fd)
  },
  patchDoc: (id: number, p: { doc_type?: string; version_label?: string; version_major?: number }) => req<Doc>('PATCH', `/api/documents/${id}`, p),
  deleteDoc: (id: number) => req<{ ok: boolean }>('DELETE', `/api/documents/${id}`),
  segments: (id: number) => req<{ document: Doc; segments: Segment[] }>('GET', `/api/documents/${id}/segments`),
  startCheck: (pid: number, force = false) => req<Job>('POST', `/api/projects/${pid}/check?force=${force}`),
  checkStatus: (pid: number) => req<Job>('GET', `/api/projects/${pid}/check`),
  facts: (pid: number) => req<{ documents: Doc[]; rows: FactRow[] }>('GET', `/api/projects/${pid}/facts`),
  findings: (pid: number) => req<Finding[]>('GET', `/api/projects/${pid}/findings`),
  review: (fid: number, decision: 'confirm' | 'dismiss', comment: string, final = false) =>
    req<Finding>('POST', `/api/findings/${fid}/review`, { decision, comment, final }),
  audit: (projectId?: number) => req<AuditEntry[]>('GET', `/api/audit${projectId ? `?project_id=${projectId}` : ''}`),
  deid: (pid: number) => req<{ token: string; kind: string; original: string }[]>('GET', `/api/projects/${pid}/deid`),
  purge: () => req<{ removed: number }>('POST', '/api/admin/purge'),
  workflows: () => req<{ templates: WfTemplate[]; roles: Record<string, string>; conditions: Record<string, string>; users: { id: number; name: string; role: string }[] }>('GET', '/api/workflows'),
  createWorkflow: (t: Omit<WfTemplate, 'id'>) => req<WfTemplate>('POST', '/api/workflows', t),
  updateWorkflow: (id: number, t: Omit<WfTemplate, 'id'>) => req<WfTemplate>('PUT', `/api/workflows/${id}`, t),
  precheck: (pid: number, templateId?: number) =>
    req<{ gates: Gate[]; ok: boolean; templates: WfTemplate[]; template_id: number | null; nodes: ResolvedNode[]; amount: number | null }>('GET', `/api/projects/${pid}/approval/precheck${templateId ? `?template_id=${templateId}` : ''}`),
  approvals: (pid: number) => req<Approval[]>('GET', `/api/projects/${pid}/approvals`),
  submitApproval: (pid: number, template_id: number, note: string) => req<Approval>('POST', `/api/projects/${pid}/approvals`, { template_id, note }),
  actApproval: (aid: number, action: 'approve' | 'reject' | 'comment', comment: string) => req<Approval>('POST', `/api/approvals/${aid}/act`, { action, comment }),
  withdrawApproval: (aid: number) => req<Approval>('POST', `/api/approvals/${aid}/withdraw`),
  inbox: () => req<Approval[]>('GET', '/api/approvals/inbox'),
  download: async (path: string, filename: string) => {
    const blob = await req<Blob>('GET', path)
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = filename
    a.click()
    setTimeout(() => URL.revokeObjectURL(a.href), 2000)
  },
}

export interface Job { state: 'idle' | 'running' | 'done' | 'error'; started?: string; summary: CheckSummary | null; error?: string | null }
export interface AuditEntry { id: number; ts: string; user: string; action: string; project_id: number | null; target: string; detail: Record<string, unknown> }

export const ROLE_LABEL: Record<Role, string> = { admin: '管理員', handler: '承辦人', reviewer: '覆核者', manager: '主管', legal: '法務' }
export const APPROVAL_LABEL: Record<ApprovalStatus, string> = { in_progress: '簽核中', approved: '已核准・可交付', rejected: '已退回', withdrawn: '已撤回', invalidated: '已失效' }
export const KIND_LABEL = { contradiction: '直接矛盾', omission: '遺漏', outdated: '疑似過期' } as const
export const SEV_LABEL = { high: '高', medium: '中', low: '低' } as const
export const STATUS_LABEL = { open: '待確認', confirmed: '已確認', dismissed: '已排除', disputed: '爭議待覆核' } as const
export const CLASS_LABEL: Record<number, string> = { 0: '公開', 1: '內部', 2: '機密', 3: '極機密' }

export function can(user: User | null, perm: 'upload' | 'check' | 'review' | 'admin' | 'create'): boolean {
  if (!user) return false
  if (perm === 'admin') return user.role === 'admin'
  if (perm === 'review') return ['admin', 'handler', 'reviewer'].includes(user.role)
  return user.role === 'admin' || user.role === 'handler'
}
