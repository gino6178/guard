import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Inbox as InboxIcon } from 'lucide-react'
import { api, type Approval } from '../api'
import { Empty, timeAgo } from '../components/ui'
import { fmtNT } from '../util'

export default function Inbox({ onChange }: { onChange?: () => void }) {
  const [items, setItems] = useState<Approval[] | null>(null)
  useEffect(() => { api.inbox().then(x => { setItems(x); onChange?.() }) }, [])

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>待我簽核</h1>
          <p className="muted">輪到你簽核的交付案件。核准前請確認送簽快照中的文件與檢核結果。</p>
        </div>
      </header>
      {items && items.length === 0 && <div className="card"><Empty icon={<InboxIcon size={28} />} title="目前沒有待簽案件" /></div>}
      <div className="inbox">
        {items?.map(a => (
          <Link key={a.id} to={`/projects/${a.project_id}/approval`} className="card inbox-row">
            <div className="ib-main">
              <div className="row"><b className="code">DG-{String(a.id).padStart(5, '0')}</b><span className="chip ap-in_progress">待簽：{a.nodes[a.current]?.name}</span></div>
              <h3>{a.project_name}</h3>
              <div className="muted small">{a.submitted_by} {timeAgo(a.submitted_at)}送簽 · {a.template_name} · {a.snapshot.documents.length} 份文件
                {a.snapshot.total_amount != null && ` · ${fmtNT(a.snapshot.total_amount)}`}</div>
              {a.note && <div className="ib-note">「{a.note}」</div>}
            </div>
            <ArrowRight size={18} className="muted" />
          </Link>
        ))}
      </div>
    </div>
  )
}
