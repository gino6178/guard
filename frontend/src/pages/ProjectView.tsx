import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, NavLink, Route, Routes, useParams } from 'react-router-dom'
import { ChevronRight, Database, FileSignature, FileStack, ListChecks, Play, RefreshCw, Settings as SettingsIcon } from 'lucide-react'
import { api, APPROVAL_LABEL, can, type Job, type Project } from '../api'
import { useUser } from '../ctx'
import { Stat, timeAgo } from '../components/ui'
import Documents from './Documents'
import FactMaster from './FactMaster'
import Findings from './Findings'
import Settings from './Settings'
import Approval from './Approval'

export default function ProjectView() {
  const { id } = useParams()
  const pid = Number(id)
  const user = useUser()
  const [p, setP] = useState<Project | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [err, setErr] = useState('')
  const [version, setVersion] = useState(0) // bump to make tabs reload after a check
  const [elapsed, setElapsed] = useState(0)
  const poll = useRef<number | undefined>(undefined)

  const load = useCallback(() => api.project(pid).then(setP).catch(e => setErr(e.message)), [pid])

  const watch = useCallback(() => {
    window.clearInterval(poll.current)
    const t0 = Date.now()
    poll.current = window.setInterval(async () => {
      setElapsed(Math.round((Date.now() - t0) / 1000))
      const j = await api.checkStatus(pid)
      setJob(j)
      if (j.state !== 'running') {
        window.clearInterval(poll.current)
        load()
        setVersion(v => v + 1)
      }
    }, 1000)
  }, [pid, load])

  useEffect(() => {
    load()
    api.checkStatus(pid).then(j => { setJob(j.state === 'running' ? j : null); if (j.state === 'running') watch() })
    return () => window.clearInterval(poll.current)
  }, [pid, load, watch])

  const run = async (force = false) => {
    setErr('')
    try {
      setJob(await api.startCheck(pid, force))
      setElapsed(0)
      watch()
    } catch (e) { setErr((e as Error).message) }
  }

  if (!p) return <div className="page">{err ? <div className="alert error">{err}</div> : <div className="skeleton" />}</div>
  const running = job?.state === 'running'
  const lc = p.last_check
  const pending = p.findings.open + p.findings.disputed

  return (
    <div className="page">
      <div className="crumbs"><Link to="/projects">專案</Link><ChevronRight size={14} /><span>{p.name}</span></div>
      <header className="page-header">
        <div>
          <h1>{p.name}</h1>
          <div className="row">
            <span className={`chip cls-${p.classification}`}>{p.classification_label}</span>
            <span className="chip plain">{p.scenario === 'sales' ? '業務接案' : '研發專案'}</span>
            {p.deid_enabled && <span className="chip plain">已去識別化</span>}
            {p.approval && <Link to="approval" className={`chip ap-${p.approval.status}`}><FileSignature size={12} />{APPROVAL_LABEL[p.approval.status]}</Link>}
            <span className="muted small">{lc ? `最後檢核 ${timeAgo(lc.at)} · ${lc.llm ? '規則＋語意比對' : '僅規則'}` : '尚未檢核'}</span>
          </div>
        </div>
        {can(user, 'check') && (
          <div className="row">
            <button className="btn ghost" disabled={running || !p.documents} onClick={() => run(true)} title="重新抽取所有文件的事實後再檢核"><RefreshCw size={16} />全部重新抽取</button>
            <button className="btn primary" disabled={running || !p.documents} onClick={() => run(false)}>
              {running ? <><span className="spinner" />檢核中 {elapsed}s</> : <><Play size={16} />執行跨文件檢核</>}
            </button>
          </div>
        )}
      </header>

      {running && (
        <div className="run-banner">
          <span className="spinner" />
          <div><b>正在檢核</b><span>解析文件、校正 OCR、抽取事實、跨文件比對與語意判定…（通常 30–60 秒）</span></div>
          <div className="indeterminate"><span /></div>
        </div>
      )}
      {err && <div className="alert error">{err}</div>}
      {job?.state === 'error' && <div className="alert error">檢核失敗：{job.error}</div>}
      {job?.state === 'done' && job.summary && (
        <div className="alert ok">
          檢核完成：{job.summary.facts} 筆事實、{job.summary.findings} 項警示（矛盾 {job.summary.by_kind.contradiction}、遺漏 {job.summary.by_kind.omission}、疑似過期 {job.summary.by_kind.outdated}），耗時 {job.summary.seconds} 秒。
          {!job.summary.llm && ' 語意模型未連線，本次僅以規則檢核。'}
        </div>
      )}

      <div className="stats-row">
        <Stat label="文件" value={p.documents} sub={`${p.doc_types.length} 種文件類型`} />
        <Stat label="事實" value={lc?.facts ?? '—'} sub="可追溯至原文" />
        <Stat label="待處理警示" value={pending} tone={pending ? 'warn' : ''} sub={`高 ${p.pending_by_severity.high} · 中 ${p.pending_by_severity.medium} · 低 ${p.pending_by_severity.low}`} />
        <Stat label="已確認／已排除" value={`${p.findings.confirmed} / ${p.findings.dismissed}`} tone="ok" sub={p.findings.disputed ? `${p.findings.disputed} 項爭議待裁定` : '雙人覆核'} />
      </div>

      <nav className="tabs">
        <NavLink to="" end><FileStack size={16} />文件</NavLink>
        <NavLink to="facts"><Database size={16} />事實主檔</NavLink>
        <NavLink to="findings"><ListChecks size={16} />衝突清單{pending > 0 && <span className="badge">{pending}</span>}</NavLink>
        <NavLink to="approval"><FileSignature size={16} />交付簽核{p.approval?.status === 'in_progress' && <span className="badge info">簽核中</span>}</NavLink>
        <NavLink to="settings"><SettingsIcon size={16} />設定</NavLink>
      </nav>
      <Routes>
        <Route path="" element={<Documents pid={pid} onChange={load} key={`d${version}`} />} />
        <Route path="facts" element={<FactMaster pid={pid} key={`f${version}`} />} />
        <Route path="findings" element={<Findings project={p} onChange={load} key={`r${version}`} />} />
        <Route path="approval" element={<Approval project={p} onChange={load} key={`a${version}`} />} />
        <Route path="settings" element={<Settings project={p} onChange={load} />} />
      </Routes>
    </div>
  )
}
