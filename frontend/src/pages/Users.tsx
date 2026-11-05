import { useEffect, useState, type FormEvent } from 'react'
import { api, CLASS_LABEL, ROLE_LABEL, type Role, type User } from '../api'

const blank = { username: '', display_name: '', password: '', role: 'handler' as Role, clearance: 1, active: true }

export default function Users() {
  const [users, setUsers] = useState<User[]>([])
  const [form, setForm] = useState(blank)
  const [editing, setEditing] = useState<number | null>(null)
  const [err, setErr] = useState('')

  const load = () => api.users().then(setUsers)
  useEffect(() => { load() }, [])

  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr('')
    try {
      if (editing) await api.updateUser(editing, { ...form, password: form.password || undefined })
      else await api.createUser(form)
      setForm(blank); setEditing(null); load()
    } catch (e) { setErr((e as Error).message) }
  }

  return (
    <div className="page">
      <div className="page-header"><h1>使用者與權限</h1></div>
      <form className="card form-grid" onSubmit={submit}>
        <label>帳號<input required disabled={!!editing} value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} /></label>
        <label>顯示名稱<input required value={form.display_name} onChange={e => setForm({ ...form, display_name: e.target.value })} /></label>
        <label>角色
          <select value={form.role} onChange={e => setForm({ ...form, role: e.target.value as Role })}>
            {Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label>可存取等級
          <select value={form.clearance} onChange={e => setForm({ ...form, clearance: +e.target.value })}>
            {Object.entries(CLASS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}（含以下）</option>)}
          </select>
        </label>
        <label>{editing ? '新密碼（留空不變）' : '密碼（至少 8 碼）'}<input type="password" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} /></label>
        <label className="check"><input type="checkbox" checked={form.active} onChange={e => setForm({ ...form, active: e.target.checked })} />啟用</label>
        <div className="span2 row">
          <button className="btn primary">{editing ? '儲存' : '新增使用者'}</button>
          {editing && <button type="button" className="btn ghost" onClick={() => { setEditing(null); setForm(blank) }}>取消</button>}
        </div>
        {err && <div className="alert error span2">{err}</div>}
      </form>
      <div className="card flush table-wrap"><table className="table">
        <thead><tr><th>帳號</th><th>名稱</th><th>角色</th><th>可存取等級</th><th>狀態</th><th /></tr></thead>
        <tbody>
          {users.map(u => (
            <tr key={u.id}>
              <td>{u.username}</td><td>{u.display_name}</td><td>{ROLE_LABEL[u.role]}</td><td>{CLASS_LABEL[u.clearance]}</td>
              <td>{u.active ? '啟用' : <span className="muted">停用</span>}</td>
              <td><button className="btn ghost sm" onClick={() => { setEditing(u.id); setForm({ ...u, password: '' }) }}>編輯</button></td>
            </tr>
          ))}
        </tbody>
      </table></div>
      <div className="card small muted">
        <b>角色說明</b>：承辦人可上傳文件、執行檢核、確認／排除警示與匯出；覆核者可覆核警示並對爭議項做最終裁定；管理員另可管理帳號、保存期限、稽核日誌與去識別化對照。
        使用者只能看到機密等級不高於其可存取等級的專案。
      </div>
    </div>
  )
}
