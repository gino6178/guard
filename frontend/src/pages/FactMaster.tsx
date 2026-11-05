import { useEffect, useState } from 'react'
import { Database, Sparkles } from 'lucide-react'
import { api, type Doc, type FactRow } from '../api'
import { Empty, FileBadge } from '../components/ui'

export default function FactMaster({ pid }: { pid: number }) {
  const [data, setData] = useState<{ documents: Doc[]; rows: FactRow[] } | null>(null)
  const [onlyDiff, setOnlyDiff] = useState(false)
  const [showOld, setShowOld] = useState(false)
  const [showItems, setShowItems] = useState(true)

  useEffect(() => { api.facts(pid).then(setData) }, [pid])
  if (!data) return <div className="skeleton" />
  if (!data.rows.length) return <div className="card"><Empty icon={<Database size={28} />} title="尚無事實">上傳文件並執行檢核後，這裡會列出每個欄位在各文件中的寫法。</Empty></div>

  const docs = data.documents.filter(d => showOld || d.is_latest)
  const rows = data.rows.filter(r => (!onlyDiff || !r.consistent) && (showItems || !r.item))
  const docName = (id: number) => data.documents.find(d => d.id === id)?.filename ?? ''
  const diffs = data.rows.filter(r => !r.consistent).length

  return (
    <div>
      <div className="toolbar">
        <div className="segmented">
          <button className={!onlyDiff ? 'on' : ''} onClick={() => setOnlyDiff(false)}>全部欄位<em>{data.rows.length}</em></button>
          <button className={onlyDiff ? 'on' : ''} onClick={() => setOnlyDiff(true)}>寫法不同<em>{diffs}</em></button>
        </div>
        <label className="check"><input type="checkbox" checked={showItems} onChange={e => setShowItems(e.target.checked)} />顯示品項明細</label>
        <label className="check"><input type="checkbox" checked={showOld} onChange={e => setShowOld(e.target.checked)} />顯示舊版文件</label>
        <span className="muted small">「寫法不同」包含同義寫法，是否矛盾以衝突清單為準。</span>
      </div>
      <div className="card flush table-wrap">
        <table className="table facts">
          <thead>
            <tr>
              <th className="sticky">欄位</th>
              <th>基準值</th>
              {docs.map(d => (
                <th key={d.id} className={d.is_latest ? '' : 'old'} title={d.filename}>
                  <div className="th-doc"><FileBadge fmt={d.fmt} /><div>{d.doc_type_label}<span>{d.version_label}</span></div></div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const ref = r.reference ? r.values[String(r.reference.doc_id)]?.[0]?.norm : undefined
              return (
                <tr key={r.field + r.item} className={r.consistent ? '' : 'diff'}>
                  <td className="sticky"><b>{r.label}</b>{r.item && <div className="small muted">{r.item}</div>}</td>
                  <td className="ref">{r.reference ? <>{r.reference.value}<div className="muted small">{docName(r.reference.doc_id)}</div></> : '—'}</td>
                  {docs.map(d => {
                    const cells = r.values[String(d.id)]
                    return (
                      <td key={d.id} className={d.is_latest ? '' : 'old'}>
                        {cells?.map((c, i) => (
                          <div key={i} className={`cell ${ref !== undefined && c.norm !== ref ? 'off' : ''}`} title={`${c.locator}\n${c.quote}`}>
                            {c.value}{c.source === 'llm' && <Sparkles size={11} className="ai" aria-label="語意模型抽取" />}
                          </div>
                        )) ?? <span className="muted">—</span>}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
