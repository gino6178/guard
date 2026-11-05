import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, ArrowRight, CheckCircle2, FileStack, FolderKanban } from 'lucide-react'
import { api, type Project } from '../api'
import { useUser } from '../ctx'
import { Empty, Stat, StackBar, timeAgo } from '../components/ui'

export default function Dashboard() {
  const user = useUser()
  const [ps, setPs] = useState<Project[] | null>(null)
  useEffect(() => { api.projects().then(setPs) }, [])
  if (!ps) return <div className="page"><div className="skeleton" /></div>

  const sum = (f: (p: Project) => number) => ps.reduce((a, p) => a + f(p), 0)
  const pending = sum(p => p.findings.open + p.findings.disputed)
  const high = sum(p => p.pending_by_severity.high)
  const confirmed = sum(p => p.findings.confirmed)
  const reviewed = confirmed + sum(p => p.findings.dismissed)
  const total = reviewed + pending
  const kinds = { contradiction: sum(p => p.pending_by_kind.contradiction), omission: sum(p => p.pending_by_kind.omission), outdated: sum(p => p.pending_by_kind.outdated) }
  const ranked = [...ps].sort((a, b) => (b.pending_by_severity.high * 10 + b.findings.open + b.findings.disputed) - (a.pending_by_severity.high * 10 + a.findings.open + a.findings.disputed))
  const recent = [...ps].filter(p => p.last_check).sort((a, b) => b.last_check!.at.localeCompare(a.last_check!.at)).slice(0, 5)
  const hour = new Date().getHours()

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>{hour < 12 ? '早安' : hour < 18 ? '午安' : '晚安'}，{user.display_name}</h1>
          <p className="muted">{pending ? `目前有 ${pending} 項警示等待確認，其中 ${high} 項為高嚴重度。` : '目前沒有待處理的警示。'}</p>
        </div>
        <Link to="/projects" className="btn primary">前往專案 <ArrowRight size={16} /></Link>
      </header>

      <div className="stats-row">
        <Stat label="專案" value={ps.length} sub={`${sum(p => p.documents)} 份文件`} icon={<FolderKanban size={18} />} />
        <Stat label="待處理警示" value={pending} tone={pending ? 'warn' : ''} sub={<StackBar parts={[
          { value: kinds.contradiction, cls: 'k-contradiction', label: '直接矛盾' },
          { value: kinds.omission, cls: 'k-omission', label: '遺漏' },
          { value: kinds.outdated, cls: 'k-outdated', label: '疑似過期' }]} />} icon={<AlertTriangle size={18} />} />
        <Stat label="高嚴重度" value={high} tone={high ? 'danger' : ''} sub="客戶名稱、金額、交期等" icon={<AlertTriangle size={18} />} />
        <Stat label="已確認問題" value={confirmed} tone="ok" sub={total ? `覆核進度 ${Math.round(reviewed / total * 100)}%` : '尚無警示'} icon={<CheckCircle2 size={18} />} />
      </div>

      {ps.length === 0 ? (
        <div className="card"><Empty icon={<FileStack size={28} />} title="還沒有專案">到「專案」建立第一個專案並上傳文件。</Empty></div>
      ) : (
        <div className="grid-2">
          <section className="card">
            <div className="card-head"><h3>風險排序</h3><span className="muted small">依待處理與高嚴重度警示</span></div>
            <ul className="rank">
              {ranked.slice(0, 6).map(p => {
                const open = p.findings.open + p.findings.disputed
                return (
                  <li key={p.id}>
                    <Link to={`/projects/${p.id}/findings`}>
                      <div className="rank-main">
                        <b>{p.name}</b>
                        <span className="muted small">{p.scenario === 'sales' ? '業務接案' : '研發專案'} · {p.documents} 份文件</span>
                      </div>
                      <div className="rank-bar">
                        <StackBar parts={[
                          { value: p.pending_by_severity.high, cls: 's-high', label: '高' },
                          { value: p.pending_by_severity.medium, cls: 's-medium', label: '中' },
                          { value: p.pending_by_severity.low, cls: 's-low', label: '低' }]} />
                      </div>
                      <span className={`count ${open ? 'warn' : 'ok'}`}>{open || <CheckCircle2 size={16} />}</span>
                    </Link>
                  </li>
                )
              })}
            </ul>
          </section>
          <section className="card">
            <div className="card-head"><h3>最近檢核</h3></div>
            <ul className="timeline">
              {recent.length === 0 && <li className="muted">尚未執行檢核</li>}
              {recent.map(p => (
                <li key={p.id}>
                  <i />
                  <div>
                    <Link to={`/projects/${p.id}`}><b>{p.name}</b></Link>
                    <div className="muted small">
                      {timeAgo(p.last_check!.at)} · {p.last_check!.facts} 筆事實 · {p.last_check!.findings} 項警示 · {p.last_check!.seconds} 秒
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </div>
  )
}
