import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, FolderPlus, Search, X } from 'lucide-react'
import { api, APPROVAL_LABEL, can, CLASS_LABEL, type Project } from '../api'
import { useUser } from '../ctx'
import { Empty, StackBar, timeAgo } from '../components/ui'

export default function Projects() {
  const user = useUser()
  const [items, setItems] = useState<Project[] | null>(null)
  const [show, setShow] = useState(false)
  const [q, setQ] = useState('')
  const [scenario, setScenario] = useState('')
  const [err, setErr] = useState('')
  const [form, setForm] = useState({ name: '', scenario: 'sales', classification: 1, retention_days: 180, deid_enabled: true })

  const load = () => api.projects().then(setItems).catch(e => setErr(e.message))
  useEffect(() => { load() }, [])

  const create = async (e: FormEvent) => {
    e.preventDefault()
    try {
      await api.createProject(form)
      setShow(false)
      setForm({ ...form, name: '' })
      load()
    } catch (e) { setErr((e as Error).message) }
  }

  const shown = (items ?? []).filter(p => (!q || p.name.includes(q)) && (!scenario || p.scenario === scenario))

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>專案</h1>
          <p className="muted">每個專案集中一組交付文件，檢核在專案內跨文件進行。</p>
        </div>
        {can(user, 'create') && <button className="btn primary" onClick={() => setShow(true)}><FolderPlus size={16} />新增專案</button>}
      </header>
      {err && <div className="alert error">{err}</div>}

      <div className="toolbar">
        <div className="search"><Search size={16} /><input placeholder="搜尋專案名稱" value={q} onChange={e => setQ(e.target.value)} /></div>
        <div className="segmented">
          {[['', '全部'], ['sales', '業務接案'], ['rnd', '研發專案']].map(([k, v]) => (
            <button key={k} className={scenario === k ? 'on' : ''} onClick={() => setScenario(k)}>{v}</button>
          ))}
        </div>
      </div>

      {items && items.length === 0 && <div className="card"><Empty icon={<FolderPlus size={28} />} title="尚無專案">建立專案後，上傳同一專案的提案、報價、合約、規格書、簡報與會議紀錄。</Empty></div>}

      <div className="project-grid">
        {shown.map(p => {
          const open = p.findings.open + p.findings.disputed
          const done = p.findings.confirmed + p.findings.dismissed
          const all = open + done
          return (
            <Link key={p.id} to={`/projects/${p.id}`} className="card project-card">
              <div className="pc-top">
                <span className={`chip cls-${p.classification}`}>{p.classification_label}</span>
                <span className="chip plain">{p.scenario === 'sales' ? '業務接案' : '研發專案'}</span>
                {p.approval && <span className={`chip ap-${p.approval.status}`}>{APPROVAL_LABEL[p.approval.status]}</span>}
              </div>
              <h3>{p.name}</h3>
              <div className="pc-metrics">
                <div><b>{p.documents}</b><span>文件</span></div>
                <div className={open ? 'warn' : ''}><b>{open}</b><span>待處理</span></div>
                <div className={p.pending_by_severity.high ? 'danger' : ''}><b>{p.pending_by_severity.high}</b><span>高嚴重度</span></div>
              </div>
              <div className="pc-progress">
                <div className="row between small"><span className="muted">覆核進度</span><span>{all ? `${done}/${all}` : '—'}</span></div>
                <div className="progress"><span style={{ width: all ? `${done / all * 100}%` : 0 }} /></div>
              </div>
              <div className="pc-foot muted small">
                {p.last_check ? <>{open === 0 && all > 0 && <CheckCircle2 size={14} className="ok-icon" />}最後檢核 {timeAgo(p.last_check.at)}</> : '尚未檢核'}
                <span>保存至 {new Date(p.retain_until).toLocaleDateString('zh-TW')}</span>
              </div>
              {open > 0 && <StackBar parts={[
                { value: p.pending_by_kind.contradiction, cls: 'k-contradiction', label: '直接矛盾' },
                { value: p.pending_by_kind.omission, cls: 'k-omission', label: '遺漏' },
                { value: p.pending_by_kind.outdated, cls: 'k-outdated', label: '疑似過期' }]} />}
            </Link>
          )
        })}
      </div>

      {show && (
        <div className="modal-bg" onClick={() => setShow(false)}>
          <form className="modal narrow" onSubmit={create} onClick={e => e.stopPropagation()}>
            <div className="modal-head"><h3>新增專案</h3><button type="button" className="icon-btn" onClick={() => setShow(false)} aria-label="關閉"><X size={18} /></button></div>
            <div className="modal-body form">
              <label>專案名稱<input required autoFocus value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="例如：智慧產線 AOI 檢測系統建置案" /></label>
              <label>工作場景</label>
              <div className="choice">
                {[['sales', '業務接案', '提案、報價、合約、會議紀錄'], ['rnd', '研發專案', '規格書、工作說明書、簡報、驗收清單']].map(([k, t, d]) => (
                  <button type="button" key={k} className={form.scenario === k ? 'on' : ''} onClick={() => setForm({ ...form, scenario: k })}><b>{t}</b><span>{d}</span></button>
                ))}
              </div>
              <div className="form-2">
                <label>機密等級
                  <select value={form.classification} onChange={e => setForm({ ...form, classification: +e.target.value })}>
                    {Object.entries(CLASS_LABEL).filter(([k]) => +k <= user.clearance).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </label>
                <label>保存期限（天）<input type="number" min={1} max={3650} value={form.retention_days} onChange={e => setForm({ ...form, retention_days: +e.target.value })} /></label>
              </div>
              <label className="check"><input type="checkbox" checked={form.deid_enabled} onChange={e => setForm({ ...form, deid_enabled: e.target.checked })} />上傳時自動去識別化（人名、電話、Email、身分證、帳號）</label>
            </div>
            <div className="modal-foot"><button type="button" className="btn ghost" onClick={() => setShow(false)}>取消</button><button className="btn primary">建立專案</button></div>
          </form>
        </div>
      )}
    </div>
  )
}
