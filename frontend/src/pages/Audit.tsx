import { useEffect, useState } from 'react'
import { api, type AuditEntry } from '../api'

const ACTION: Record<string, string> = {
  login: '登入', 'login.failed': '登入失敗', 'project.create': '建立專案', 'project.update': '更新專案', 'project.delete': '刪除專案',
  'doc.upload': '上傳文件', 'doc.delete': '刪除文件', 'doc.view': '檢視文件', 'doc.download': '下載原檔', 'doc.update': '修改文件屬性',
  'check.start': '執行檢核', 'finding.review': '覆核警示', 'export.xlsx': '匯出 Excel', 'export.docx': '匯出報告',
  'user.create': '建立使用者', 'user.update': '更新使用者', 'deid.reveal': '查看去識別化對照', 'retention.purge': '執行保存期限清除',
  'retention.expired': '逾期自動刪除',
}

export default function Audit({ projectId, embedded }: { projectId?: number; embedded?: boolean }) {
  const [rows, setRows] = useState<AuditEntry[] | null>(null)
  const [msg, setMsg] = useState('')
  const load = () => api.audit(projectId).then(setRows)
  useEffect(() => { load() }, [projectId])

  const table = (
    <div>
      <div className="card flush table-wrap"><table className="table">
        <thead><tr><th>時間</th><th>使用者</th><th>動作</th><th>對象</th><th>內容</th></tr></thead>
        <tbody>
          {rows?.map(r => (
            <tr key={r.id}>
              <td className="small nowrap">{new Date(r.ts).toLocaleString('zh-TW')}</td>
              <td>{r.user || '系統'}</td>
              <td>{ACTION[r.action] ?? r.action}</td>
              <td className="small">{r.target}{r.project_id && !projectId ? ` (專案 ${r.project_id})` : ''}</td>
              <td className="small muted">{Object.keys(r.detail).length ? JSON.stringify(r.detail) : ''}</td>
            </tr>
          ))}
        </tbody>
      </table></div>
    </div>
  )
  if (embedded) return table
  return (
    <div className="page">
      <div className="page-header">
        <h1>稽核日誌</h1>
        <button className="btn ghost" onClick={async () => { const r = await api.purge(); setMsg(`已清除 ${r.removed} 個逾期專案`); load() }}>立即執行保存期限清除</button>
      </div>
      {msg && <div className="alert ok">{msg}</div>}
      {table}
    </div>
  )
}
