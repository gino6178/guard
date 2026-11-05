import { useEffect, useRef, useState, type DragEvent } from 'react'
import { History, ScanText, Trash2, UploadCloud } from 'lucide-react'
import { api, can, type Doc, type Health } from '../api'
import { useUser } from '../ctx'
import { Empty, FileBadge } from '../components/ui'
import DocViewer from './DocViewer'

const ACCEPT = '.docx,.pdf,.xlsx,.xlsm,.pptx'

export default function Documents({ pid, onChange }: { pid: number; onChange: () => void }) {
  const user = useUser()
  const [docs, setDocs] = useState<Doc[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [msgs, setMsgs] = useState<{ ok: boolean; text: string }[]>([])
  const [drag, setDrag] = useState(false)
  const [view, setView] = useState<number | null>(null)
  const [types, setTypes] = useState<Record<string, string>>({})
  const input = useRef<HTMLInputElement>(null)

  const load = () => api.docs(pid).then(setDocs)
  useEffect(() => { load(); api.health().then((h: Health) => setTypes(h.doc_types)).catch(() => {}) }, [pid])

  const upload = async (files: File[]) => {
    if (!files.length) return
    setBusy(true); setMsgs([])
    try {
      const r = await api.upload(pid, files)
      setMsgs([
        ...(r.uploaded.length ? [{ ok: true, text: `已上傳 ${r.uploaded.length} 份文件，執行檢核以更新衝突清單。` }] : []),
        ...r.errors.map(e => ({ ok: false, text: `${e.filename}：${e.error}` })),
      ])
      load(); onChange()
    } catch (e) { setMsgs([{ ok: false, text: (e as Error).message }]) } finally { setBusy(false) }
  }

  const onDrop = (e: DragEvent) => { e.preventDefault(); setDrag(false); upload(Array.from(e.dataTransfer.files)) }
  const setType = async (d: Doc, doc_type: string) => { await api.patchDoc(d.id, { doc_type }); load() }
  const remove = async (d: Doc) => {
    if (!confirm(`刪除「${d.filename}」？相關事實與警示會在下次檢核時更新。`)) return
    await api.deleteDoc(d.id); load(); onChange()
  }

  const groups = new Map<string, Doc[]>()
  docs?.forEach(d => groups.set(d.version_group, [...(groups.get(d.version_group) ?? []), d]))
  const ordered = [...groups.values()].map(g => [...g].sort((a, b) => Number(b.is_latest) - Number(a.is_latest)))

  return (
    <div>
      {can(user, 'upload') && (
        <div className={`dropzone ${drag ? 'drag' : ''} ${busy ? 'busy' : ''}`} onDragOver={e => { e.preventDefault(); setDrag(true) }}
             onDragLeave={() => setDrag(false)} onDrop={onDrop} onClick={() => !busy && input.current?.click()}>
          <input ref={input} type="file" multiple accept={ACCEPT} hidden onChange={e => { upload(Array.from(e.target.files ?? [])); e.target.value = '' }} />
          <div className="dz-icon">{busy ? <span className="spinner lg" /> : <UploadCloud size={26} />}</div>
          <div>
            <b>{busy ? '解析中（含 OCR 與去識別化）…' : '拖曳檔案到這裡，或點擊選擇'}</b>
            <span>支援 DOCX、PDF（含掃描檔）、XLSX、PPTX · 原檔唯讀保存並記錄 SHA-256</span>
          </div>
        </div>
      )}
      {msgs.map((m, i) => <div key={i} className={`alert ${m.ok ? 'ok' : 'error'}`}>{m.text}</div>)}
      {docs && docs.length === 0 && <div className="card"><Empty icon={<UploadCloud size={28} />} title="尚未上傳文件" /></div>}

      <div className="doc-list">
        {ordered.map(g => (
          <div key={g[0].version_group} className="card doc-group">
            {g.map((d, i) => (
              <div key={d.id} className={`doc-row ${d.is_latest ? '' : 'old'} ${i > 0 ? 'sub' : ''}`}>
                <FileBadge fmt={d.fmt} />
                <div className="doc-main">
                  <button className="link strong" onClick={() => setView(d.id)}>{d.filename}</button>
                  <div className="doc-meta">
                    <span>{d.pages} {d.fmt === 'pptx' ? '張' : d.fmt === 'xlsx' ? '工作表' : '頁'}</span>
                    {d.ocr_pages > 0 && <span className="chip warn"><ScanText size={12} />OCR {d.ocr_pages} 頁</span>}
                    <span>{d.status === 'parsed' ? '待抽取' : d.status === 'extracted' ? '已抽取（規則＋語意）' : '已抽取（規則）'}</span>
                    {d.warnings.slice(-1).map((w, k) => <span key={k} className="muted">{w}</span>)}
                  </div>
                </div>
                <div className="doc-ver">
                  <span className={`chip ${d.is_latest ? 'ok' : 'plain'}`}>{d.is_latest ? '最新' : <><History size={12} />舊版</>}</span>
                  <span className="ver">{d.version_label === '未標示' ? '未標示版本' : d.version_label}</span>
                </div>
                <div className="doc-type">
                  {can(user, 'upload') ? (
                    <select value={d.doc_type} onChange={e => setType(d, e.target.value)} aria-label="文件類型">
                      {Object.entries({ [d.doc_type]: d.doc_type_label, ...types }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    </select>
                  ) : <span className="chip plain">{d.doc_type_label}</span>}
                </div>
                {can(user, 'upload') && <button className="icon-btn" onClick={() => remove(d)} title="刪除" aria-label="刪除"><Trash2 size={16} /></button>}
              </div>
            ))}
          </div>
        ))}
      </div>
      {docs && docs.length > 0 && <p className="muted small">同一文件的多個版本會自動分組；只有「最新」版參與跨文件比對，舊版用來判斷是否有文件沿用過期內容。</p>}
      {view && <DocViewer docId={view} onClose={() => setView(null)} />}
    </div>
  )
}
