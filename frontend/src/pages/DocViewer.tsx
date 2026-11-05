import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { api, type Doc, type Segment } from '../api'
import { FileBadge } from '../components/ui'

export function Highlight({ text, quote }: { text: string; quote?: string }) {
  if (!quote) return <>{text}</>
  const i = text.indexOf(quote)
  if (i < 0) return <>{text}</>
  return <>{text.slice(0, i)}<mark>{quote}</mark>{text.slice(i + quote.length)}</>
}

export default function DocViewer({ docId, highlight, onClose }: { docId: number; highlight?: string; onClose: () => void }) {
  const [data, setData] = useState<{ document: Doc; segments: Segment[] } | null>(null)
  const [raw, setRaw] = useState(false)
  const target = useRef<HTMLDivElement>(null)

  useEffect(() => { api.segments(docId).then(setData) }, [docId])
  useEffect(() => { target.current?.scrollIntoView({ block: 'center' }) }, [data])
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])

  let page: number | null | undefined
  let found = false
  const d = data?.document
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal wide" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <div className="row">
            {d && <FileBadge fmt={d.fmt} />}
            <div>
              <h3>{d?.filename ?? '載入中…'}</h3>
              {d && <span className="muted small">{d.doc_type_label} · {d.version_label} · SHA-256 {d.sha256.slice(0, 12)}…</span>}
            </div>
          </div>
          <div className="row">
            {data?.segments.some(s => s.raw_text) && (
              <label className="check small"><input type="checkbox" checked={raw} onChange={e => setRaw(e.target.checked)} />顯示 OCR 原始辨識</label>
            )}
            <button className="icon-btn" onClick={onClose} aria-label="關閉"><X size={18} /></button>
          </div>
        </div>
        <div className="modal-body paper">
          {data?.segments.map(s => {
            const header = s.page !== page ? <div className="page-mark"><span>第 {s.page} {d!.fmt === 'pptx' ? '張投影片' : d!.fmt === 'xlsx' ? '個工作表' : '頁'}</span></div> : null
            page = s.page
            const hit = !!highlight && !found && s.text.includes(highlight)
            if (hit) found = true
            return (
              <div key={s.id}>
                {header}
                <div className={`seg ${hit ? 'hit' : ''}`} ref={hit ? target : undefined}>
                  <span className="loc">{s.locator.replace(/^第\d+(頁|張投影片)\s*/, '')}{s.ocr && <em>OCR</em>}</span>
                  <span><Highlight text={raw && s.raw_text ? s.raw_text : s.text} quote={hit ? highlight : undefined} /></span>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
