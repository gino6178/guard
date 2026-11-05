import { useEffect, useMemo, useState } from 'react'
import { Check, CheckCircle2, Download, FileText, Gavel, Search, Sparkles, X } from 'lucide-react'
import { api, can, KIND_LABEL, STATUS_LABEL, type Evidence, type Finding, type Project } from '../api'
import { useUser } from '../ctx'
import { Empty, FileBadge, fmtFromName, KindChip, SevChip, StatusChip } from '../components/ui'
import DocViewer, { Highlight } from './DocViewer'

type Filter = { kind: string; status: string; q: string }

export default function Findings({ project, onChange }: { project: Project; onChange: () => void }) {
  const [items, setItems] = useState<Finding[] | null>(null)
  const [filter, setFilter] = useState<Filter>({ kind: '', status: 'pending', q: '' })
  const [sel, setSel] = useState<number | null>(null)
  const [view, setView] = useState<{ id: number; highlight?: string } | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => { api.findings(project.id).then(setItems).catch(e => setErr(e.message)) }, [project.id])

  const shown = useMemo(() => (items ?? []).filter(f =>
    (!filter.kind || f.kind === filter.kind) &&
    (!filter.status || (filter.status === 'pending' ? f.status === 'open' || f.status === 'disputed' : f.status === filter.status)) &&
    (!filter.q || (f.title + f.item + f.detail).includes(filter.q))), [items, filter])

  const current = shown.find(f => f.id === sel) ?? shown[0]

  // j / k to move through the list
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === 'INPUT' || view) return
      const i = shown.findIndex(f => f.id === current?.id)
      if (e.key === 'j' || e.key === 'ArrowDown') { setSel(shown[Math.min(i + 1, shown.length - 1)]?.id ?? null); e.preventDefault() }
      if (e.key === 'k' || e.key === 'ArrowUp') { setSel(shown[Math.max(i - 1, 0)]?.id ?? null); e.preventDefault() }
    }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [shown, current, view])

  const update = (f: Finding) => {
    setItems(xs => xs?.map(x => x.id === f.id ? f : x) ?? null)
    onChange()
  }

  const count = (pred: (f: Finding) => boolean) => (items ?? []).filter(pred).length
  const exportName = project.name.replace(/[\\/:*?"<>|]/g, '_')

  return (
    <div>
      <div className="toolbar">
        <div className="segmented">
          {[['pending', '待處理', count(f => f.status === 'open' || f.status === 'disputed')],
            ['confirmed', STATUS_LABEL.confirmed, count(f => f.status === 'confirmed')],
            ['dismissed', STATUS_LABEL.dismissed, count(f => f.status === 'dismissed')],
            ['', '全部', items?.length ?? 0]].map(([k, v, n]) => (
            <button key={k} className={filter.status === k ? 'on' : ''} onClick={() => setFilter({ ...filter, status: k as string })}>{v}<em>{n}</em></button>
          ))}
        </div>
        <select value={filter.kind} onChange={e => setFilter({ ...filter, kind: e.target.value })} aria-label="類型">
          <option value="">全部類型</option>
          {Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}（{count(f => f.kind === k)}）</option>)}
        </select>
        <div className="search"><Search size={16} /><input placeholder="搜尋警示" value={filter.q} onChange={e => setFilter({ ...filter, q: e.target.value })} /></div>
        <div className="spacer" />
        <button className="btn ghost" onClick={() => api.download(`/api/projects/${project.id}/export.xlsx`, `${exportName}_衝突清單.xlsx`)}><Download size={16} />Excel</button>
        <button className="btn ghost" onClick={() => api.download(`/api/projects/${project.id}/report.docx`, `${exportName}_檢核報告.docx`)}><FileText size={16} />檢核報告</button>
      </div>
      {err && <div className="alert error">{err}</div>}

      {items && items.length === 0 && (
        <div className="card"><Empty icon={<CheckCircle2 size={28} />} title={project.last_check ? '未發現跨文件差異' : '尚未執行檢核'}>
          {project.last_check ? '最新版文件之間的事實一致。' : '上傳文件後點右上角「執行跨文件檢核」。'}
        </Empty></div>
      )}
      {items && items.length > 0 && shown.length === 0 && (
        <div className="card"><Empty icon={<CheckCircle2 size={28} />} title={filter.status === 'pending' ? '全部警示都已處理' : '沒有符合條件的警示'} /></div>
      )}

      {shown.length > 0 && (
        <div className="review">
          <ul className="review-list">
            {shown.map(f => (
              <li key={f.id} className={`${f.id === current?.id ? 'on' : ''} sev-${f.severity}`} onClick={() => setSel(f.id)}>
                <div className="rl-top"><KindChip kind={f.kind} /><SevChip sev={f.severity} />{f.status !== 'open' && <StatusChip status={f.status} />}</div>
                <div className="rl-title">{headline(f)}</div>
                {f.item && f.field !== 'version_ref' && <div className="rl-item">{f.item}</div>}
                <div className="rl-docs">
                  {[...new Set(f.evidence.map(e => e.filename))].slice(0, 4).map(n => <FileBadge key={n} fmt={fmtFromName(n)} />)}
                  <span className="muted small">{new Set(f.evidence.map(e => e.doc_id)).size} 份文件</span>
                </div>
              </li>
            ))}
          </ul>
          {current && <Detail key={current.id} f={current} onUpdate={update} onOpen={(id, q) => setView({ id, highlight: q })} />}
        </div>
      )}
      <p className="muted small kbd-hint">提示：按 <kbd>J</kbd>／<kbd>K</kbd> 切換警示。</p>
      {view && <DocViewer docId={view.id} highlight={view.highlight} onClose={() => setView(null)} />}
    </div>
  )
}

function Detail({ f, onUpdate, onOpen }: { f: Finding; onUpdate: (f: Finding) => void; onOpen: (docId: number, q?: string) => void }) {
  const user = useUser()
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const canFinal = f.status === 'disputed' && (user.role === 'reviewer' || user.role === 'admin')

  const decide = async (decision: 'confirm' | 'dismiss', final = false) => {
    setBusy(true); setErr('')
    try { onUpdate(await api.review(f.id, decision, comment, final)); setComment('') }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  return (
    <article className={`card detail sev-${f.severity}`}>
      <div className="row">
        <KindChip kind={f.kind} /><SevChip sev={f.severity} /><StatusChip status={f.status} />
        <span className="chip plain">{f.detector.startsWith('semantic') ? <><Sparkles size={12} />語意比對</> : '規則檢核'}</span>
        <span className="muted small">#{f.id}</span>
      </div>
      <h2>{headline(f)}{f.item && f.field !== 'version_ref' && <span className="h-item">{f.item}</span>}</h2>
      <p className="detail-sub">{f.title.includes('：') ? f.title.slice(f.title.indexOf('：') + 1) : ''}</p>
      <p className="detail-desc">{f.detail}</p>

      <div className="ev-head">原文證據 <span className="muted">· 點檔名開啟原文定位</span></div>
      <div className="evidence-grid">
        {f.evidence.map((e, i) => <EvidenceCard key={i} e={e} onOpen={onOpen}
          differs={!!e.value && !!f.evidence[0].value && norm(e.value) !== norm(f.evidence[0].value)} />)}
      </div>

      {f.reviews.length > 0 && (
        <div className="history">
          <div className="ev-head">覆核紀錄</div>
          <ol>
            {f.reviews.map((r, i) => (
              <li key={i} className={r.decision}>
                <span className="dot">{r.final ? <Gavel size={12} /> : r.decision === 'confirm' ? <Check size={12} /> : <X size={12} />}</span>
                <div>
                  <b>{r.user}</b>{r.final ? ' 最終裁定為' : ' 判定為'}{r.decision === 'confirm' ? '「確認問題」' : '「排除」'}
                  {r.comment && <div className="quote">{r.comment}</div>}
                  <div className="muted small">{new Date(r.at).toLocaleString('zh-TW')}</div>
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}

      {can(user, 'review') && (
        <div className="decide">
          <textarea rows={2} placeholder={canFinal ? '裁定說明…' : '備註（排除時必填，例如：同義寫法、已於他處更正）'} value={comment} onChange={e => setComment(e.target.value)} />
          <div className="row end">
            {canFinal ? (
              <>
                <button className="btn ghost" disabled={busy || !comment.trim()} onClick={() => decide('dismiss', true)}><Gavel size={16} />裁定：排除</button>
                <button className="btn primary" disabled={busy} onClick={() => decide('confirm', true)}><Gavel size={16} />裁定：確認</button>
              </>
            ) : (
              <>
                <button className="btn ghost" disabled={busy || !comment.trim()} onClick={() => decide('dismiss')} title="排除需填寫理由"><X size={16} />排除（誤報）</button>
                <button className="btn primary" disabled={busy} onClick={() => decide('confirm')}><Check size={16} />確認為問題</button>
              </>
            )}
          </div>
          {f.status === 'disputed' && !canFinal && <p className="muted small">此項覆核意見不一致，待覆核者最終裁定。</p>}
          {err && <div className="alert error">{err}</div>}
        </div>
      )}
    </article>
  )
}

const norm = (v: string) => v.replace(/[\s,，、:：()（）]/g, '').replace(/股份有限公司|有限公司/g, '').toLowerCase()

/** Short headline: the part before the first full-width colon, minus the item in parentheses. */
function headline(f: Finding) {
  const head = f.title.includes('：') ? f.title.slice(0, f.title.indexOf('：')) : f.title
  return head.replace(`（${f.item}）`, '')
}

function EvidenceCard({ e, onOpen, differs }: { e: Evidence; onOpen: (docId: number, q?: string) => void; differs: boolean }) {
  return (
    <div className={`ev-card ${e.note === '舊版來源' ? 'old' : ''} ${!e.text ? 'missing' : ''} ${differs ? 'differs' : ''}`}>
      <div className="ev-src">
        <FileBadge fmt={fmtFromName(e.filename)} />
        <div>
          <button className="link strong" onClick={() => onOpen(e.doc_id, e.quote || undefined)}>{e.filename}</button>
          <div className="muted small">{e.doc_type} · {e.version} · {e.locator}</div>
        </div>
        {e.note && <span className="chip plain">{e.note}</span>}
      </div>
      {e.value && e.text && <div className="ev-value">{e.value}</div>}
      {e.text ? <blockquote><Highlight text={e.text} quote={e.quote} /></blockquote>
              : <blockquote className="muted">{e.value ? `文件版本：${e.value}` : '此文件中未見此項'}</blockquote>}
    </div>
  )
}
