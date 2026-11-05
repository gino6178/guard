import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertCircle, CheckCircle2, CornerUpLeft, FileSignature, MessageSquare, ShieldCheck, Undo2, XCircle } from 'lucide-react'
import { api, can, type Approval as ApprovalT, type Gate, type Project, type ResolvedNode, type WfTemplate } from '../api'
import { useUser } from '../ctx'
import Flow from '../components/Flow'
import { FileBadge, fmtFromName } from '../components/ui'
import { fmtNT } from '../util'

type Pre = { gates: Gate[]; ok: boolean; templates: WfTemplate[]; template_id: number | null; nodes: ResolvedNode[]; amount: number | null }

export default function Approval({ project, onChange }: { project: Project; onChange: () => void }) {
  const user = useUser()
  const [pre, setPre] = useState<Pre | null>(null)
  const [list, setList] = useState<ApprovalT[] | null>(null)
  const [tpl, setTpl] = useState<number | undefined>()
  const [note, setNote] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const load = (templateId?: number) => {
    api.precheck(project.id, templateId).then(p => { setPre(p); setTpl(p.template_id ?? undefined) })
    api.approvals(project.id).then(setList)
  }
  useEffect(() => { load() }, [project.id])

  const active = list?.find(a => a.status === 'in_progress')
  const approved = list?.[0]?.status === 'approved'  // latest sign-off still valid
  const submit = async () => {
    if (!tpl) return
    setBusy(true); setErr('')
    try { await api.submitApproval(project.id, tpl, note); setNote(''); load(tpl); onChange() }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const update = (a: ApprovalT) => { setList(xs => xs?.map(x => x.id === a.id ? a : x) ?? null); onChange() }

  if (!pre || !list) return <div className="skeleton" />

  return (
    <div className="approval">
      {!active && !approved && (
        <section className="card">
          <div className="card-head">
            <h3><FileSignature size={18} />送出交付簽核</h3>
            {pre.amount != null && <span className="muted small">總金額（含稅）{fmtNT(pre.amount)}</span>}
          </div>
          <div className="gates">
            {pre.gates.map(g => (
              <div key={g.key} className={`gate ${g.ok ? 'ok' : 'no'}`}>
                {g.ok ? <CheckCircle2 size={18} /> : <XCircle size={18} />}
                <div><b>{g.label}</b><span>{g.detail}</span></div>
                {!g.ok && g.key === 'pending' && <Link to="../findings" className="btn ghost sm">前往處理</Link>}
                {!g.ok && (g.key === 'checked' || g.key === 'documents') && <Link to=".." className="btn ghost sm">前往文件</Link>}
              </div>
            ))}
          </div>

          <div className="submit-area">
            <div className="row between">
              <label className="tpl-pick">簽核流程
                <select value={tpl} onChange={e => load(+e.target.value)}>
                  {pre.templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
              </label>
              {user.role === 'admin' && <Link to="/workflows" className="link small">管理簽核流程範本</Link>}
            </div>
            {pre.nodes.length > 0 && <Flow nodes={pre.nodes} submitter={user.display_name} />}
            {can(user, 'upload') && (
              <>
                <textarea rows={2} placeholder="送簽說明（選填），例如：本次交付內容與注意事項" value={note} onChange={e => setNote(e.target.value)} />
                <div className="row end">
                  {!pre.ok && <span className="muted small"><AlertCircle size={14} className="vmid" /> 尚有條件未通過，無法送簽</span>}
                  <button className="btn primary" disabled={!pre.ok || busy || !tpl} onClick={submit}><FileSignature size={16} />送出簽核</button>
                </div>
              </>
            )}
            {err && <div className="alert error">{err}</div>}
            <p className="muted small">送簽時會凍結文件指紋與檢核結果；送簽後若文件有任何變動，進行中或已核准的簽核會自動失效，需重新檢核並送簽。</p>
          </div>
        </section>
      )}

      {list.map(a => <ApprovalCard key={a.id} a={a} onUpdate={update} onWithdrawn={() => { load(tpl); onChange() }} />)}
      {list.length === 0 && pre.templates.length === 0 && <div className="alert error">尚無可用的簽核流程範本，請管理員建立。</div>}
    </div>
  )
}

function ApprovalCard({ a, onUpdate, onWithdrawn }: { a: ApprovalT; onUpdate: (a: ApprovalT) => void; onWithdrawn: () => void }) {
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState(a.status === 'in_progress')

  const doAct = async (action: 'approve' | 'reject' | 'comment') => {
    setBusy(true); setErr('')
    try { onUpdate(await api.actApproval(a.id, action, comment)); setComment(''); window.dispatchEvent(new Event('dg:inbox')) }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const withdraw = async () => {
    if (!confirm('撤回此簽核？')) return
    try { await api.withdrawApproval(a.id); onWithdrawn() } catch (e) { setErr((e as Error).message) }
  }
  const code = `DG-${String(a.id).padStart(5, '0')}`

  return (
    <section className={`card approval-card st-${a.status}`}>
      <div className="ac-head" onClick={() => setOpen(!open)}>
        <div>
          <div className="row"><b className="code">{code}</b><span className={`chip ap-${a.status}`}>{a.status_label}</span><span className="muted small">{a.template_name}</span></div>
          <div className="muted small">{a.submitted_by} 於 {new Date(a.submitted_at).toLocaleString('zh-TW')} 送簽{a.status_reason && ` · ${a.status_reason}`}</div>
        </div>
        <div className="row" onClick={e => e.stopPropagation()}>
          <button className="btn ghost sm" onClick={() => api.download(`/api/approvals/${a.id}/form.docx`, `交付簽核單_${code}.docx`)}>簽核單</button>
          {a.can_withdraw && <button className="btn ghost sm" onClick={withdraw}><Undo2 size={14} />撤回</button>}
        </div>
      </div>
      <Flow nodes={a.nodes} approval={a} submitter={a.submitted_by} />
      {open && (
        <>
          {a.note && <blockquote>送簽說明：{a.note}</blockquote>}
          <div className="ac-grid">
            <div>
              <div className="ev-head">送簽快照 · {a.snapshot.documents.length} 份文件</div>
              <ul className="snap-docs">
                {a.snapshot.documents.map(d => (
                  <li key={d.sha256 + d.filename}><FileBadge fmt={fmtFromName(d.filename)} /><span>{d.filename}</span><code title={d.sha256}>{d.sha256.slice(0, 10)}</code></li>
                ))}
              </ul>
              <div className="muted small">內容指紋 <code>{a.snapshot_hash.slice(0, 24)}…</code> · 警示已確認 {a.snapshot.findings.confirmed}／已排除 {a.snapshot.findings.dismissed}</div>
            </div>
            <div>
              <div className="ev-head">簽核紀錄</div>
              {a.steps.length === 0 && <div className="muted small">尚無簽核紀錄</div>}
              <ol className="history">
                {a.steps.map((s, i) => (
                  <li key={i} className={s.action === 'approve' ? 'confirm' : s.action === 'reject' ? 'reject' : 'comment'}>
                    <span className="dot">{s.action === 'approve' ? <ShieldCheck size={12} /> : s.action === 'reject' ? <CornerUpLeft size={12} /> : <MessageSquare size={12} />}</span>
                    <div>
                      <b>{s.user}</b> {s.action === 'approve' ? '核准' : s.action === 'reject' ? '退回' : '留言'}「{s.node_name}」
                      {s.comment && <div className="quote">{s.comment}</div>}
                      <div className="muted small">{new Date(s.at).toLocaleString('zh-TW')} · 簽章 <code>{s.signature.slice(0, 12)}</code></div>
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          </div>
          {a.status === 'in_progress' && (
            <div className="decide">
              <textarea rows={2} placeholder={a.can_act ? '簽核意見（退回時必填）' : '留言'} value={comment} onChange={e => setComment(e.target.value)} />
              <div className="row end">
                <button className="btn ghost" disabled={busy || !comment.trim()} onClick={() => doAct('comment')}><MessageSquare size={16} />留言</button>
                {a.can_act && <>
                  <button className="btn ghost danger-text" disabled={busy || !comment.trim()} onClick={() => doAct('reject')}><CornerUpLeft size={16} />退回</button>
                  <button className="btn primary" disabled={busy} onClick={() => doAct('approve')}><ShieldCheck size={16} />核准「{a.nodes[a.current]?.name}」</button>
                </>}
              </div>
              {!a.can_act && <p className="muted small">目前關卡「{a.nodes[a.current]?.name}」由 {a.nodes[a.current]?.assignee_label} 簽核。</p>}
              {err && <div className="alert error">{err}</div>}
            </div>
          )}
        </>
      )}
    </section>
  )
}
