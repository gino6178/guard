import type { ReactNode } from 'react'
import { KIND_LABEL, SEV_LABEL, STATUS_LABEL, type Finding } from '../api'

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg viewBox="0 0 32 32" width={size} height={size} aria-hidden>
      <defs>
        <linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#5b8cff" /><stop offset="1" stopColor="#2f5fd0" />
        </linearGradient>
      </defs>
      <path d="M16 2 4 7v8c0 7.5 5.1 13.4 12 15 6.9-1.6 12-7.5 12-15V7z" fill="url(#lg)" />
      <path d="m10.5 16 4 4 7-8" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

const FMT: Record<string, { label: string; cls: string }> = {
  docx: { label: 'DOC', cls: 'f-doc' }, pdf: { label: 'PDF', cls: 'f-pdf' },
  xlsx: { label: 'XLS', cls: 'f-xls' }, pptx: { label: 'PPT', cls: 'f-ppt' },
}

export function FileBadge({ fmt }: { fmt: string }) {
  const f = FMT[fmt] ?? { label: fmt.toUpperCase().slice(0, 3), cls: '' }
  return <span className={`file-badge ${f.cls}`}>{f.label}</span>
}

export function fmtFromName(name: string) {
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  return ext === 'xlsm' ? 'xlsx' : ext
}

export function KindChip({ kind }: { kind: Finding['kind'] }) {
  return <span className={`chip kind-${kind}`}>{KIND_LABEL[kind]}</span>
}
export function SevChip({ sev }: { sev: Finding['severity'] }) {
  return <span className={`chip sev-${sev}`}><i />{SEV_LABEL[sev]}</span>
}
export function StatusChip({ status }: { status: Finding['status'] }) {
  return <span className={`chip st-${status}`}>{STATUS_LABEL[status]}</span>
}

export function Stat({ label, value, sub, tone, icon }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string; icon?: ReactNode }) {
  return (
    <div className={`stat ${tone ?? ''}`}>
      <div className="stat-top"><span>{label}</span>{icon}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      {icon && <div className="empty-icon">{icon}</div>}
      <div className="empty-title">{title}</div>
      {children && <div className="empty-body">{children}</div>}
    </div>
  )
}

/** Horizontal stacked bar, e.g. pending findings by kind. */
export function StackBar({ parts }: { parts: { value: number; cls: string; label: string }[] }) {
  const total = parts.reduce((a, p) => a + p.value, 0)
  if (!total) return <div className="stackbar empty-bar" />
  return (
    <div className="stackbar" role="img" aria-label={parts.map(p => `${p.label} ${p.value}`).join('、')}>
      {parts.filter(p => p.value).map(p => <span key={p.label} className={p.cls} style={{ flex: p.value }} title={`${p.label} ${p.value}`} />)}
    </div>
  )
}

export function timeAgo(iso: string) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 60) return '剛剛'
  if (s < 3600) return `${Math.floor(s / 60)} 分鐘前`
  if (s < 86400) return `${Math.floor(s / 3600)} 小時前`
  return new Date(iso).toLocaleDateString('zh-TW')
}
