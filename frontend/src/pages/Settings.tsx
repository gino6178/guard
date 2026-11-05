import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, CLASS_LABEL, type Project } from '../api'
import { useUser } from '../ctx'
import Audit from './Audit'

export default function Settings({ project, onChange }: { project: Project; onChange: () => void }) {
  const user = useUser()
  const nav = useNavigate()
  const [days, setDays] = useState(180)
  const [cls, setCls] = useState(project.classification)
  const [tokens, setTokens] = useState<{ token: string; kind: string; original: string }[] | null>(null)
  const [msg, setMsg] = useState('')
  const isAdmin = user.role === 'admin'
  const canEdit = user.role !== 'reviewer'

  const save = async (body: Parameters<typeof api.patchProject>[1]) => {
    try { await api.patchProject(project.id, body); setMsg('已更新'); onChange() } catch (e) { setMsg((e as Error).message) }
  }

  return (
    <div className="settings">
      <section className="card">
        <h3>資料分級與保存</h3>
        <p>機密等級：<b>{project.classification_label}</b>　去識別化：<b>{project.deid_enabled ? '啟用' : '未啟用'}</b>　保存至：<b>{new Date(project.retain_until).toLocaleDateString('zh-TW')}</b></p>
        <p className="muted small">逾保存期限的專案（含原檔、解析內容、事實與警示）由系統自動刪除；稽核日誌保留。</p>
        {canEdit && (
          <div className="row">
            <select value={cls} onChange={e => setCls(+e.target.value)}>
              {Object.entries(CLASS_LABEL).filter(([k]) => +k <= user.clearance).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <button className="btn ghost" onClick={() => save({ classification: cls })}>變更等級</button>
          </div>
        )}
        {isAdmin && (
          <div className="row">
            自今日起保存 <input type="number" min={1} value={days} onChange={e => setDays(+e.target.value)} style={{ width: 90 }} /> 天
            <button className="btn ghost" onClick={() => save({ retention_days: days })}>更新保存期限</button>
            <button className="btn danger" onClick={async () => {
              if (confirm(`永久刪除專案「${project.name}」及所有文件？此動作無法復原。`)) { await api.deleteProject(project.id); nav('/') }
            }}>立即刪除專案</button>
          </div>
        )}
        {msg && <div className="alert ok">{msg}</div>}
      </section>
      {isAdmin && project.deid_enabled && (
        <section className="card">
          <h3>去識別化對照</h3>
          <p className="muted small">僅管理員可查看；每次查看均記錄於稽核日誌。</p>
          {tokens ? (
            <div className="card flush table-wrap"><table className="table"><thead><tr><th>代碼</th><th>類型</th><th>原始值</th></tr></thead>
              <tbody>{tokens.map(t => <tr key={t.token}><td>{t.token}</td><td>{t.kind}</td><td>{t.original}</td></tr>)}</tbody></table></div>
          ) : <button className="btn ghost" onClick={() => api.deid(project.id).then(setTokens)}>顯示對照表</button>}
        </section>
      )}
      {isAdmin && <section className="card"><h3>本專案稽核紀錄</h3><Audit projectId={project.id} embedded /></section>}
    </div>
  )
}
