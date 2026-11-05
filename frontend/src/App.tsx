import { useEffect, useState } from 'react'
import { Navigate, NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { FolderKanban, GitBranch, Inbox as InboxIcon, LayoutDashboard, LogOut, ScrollText, Users as UsersIcon } from 'lucide-react'
import { api, getToken, ROLE_LABEL, setToken, type Health, type User } from './api'
import { Logo } from './components/ui'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Projects from './pages/Projects'
import ProjectView from './pages/ProjectView'
import Users from './pages/Users'
import Audit from './pages/Audit'
import Inbox from './pages/Inbox'
import Workflows from './pages/Workflows'
import { UserCtx } from './ctx'

export default function App() {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)
  const [health, setHealth] = useState<Health | null>(null)
  const [inbox, setInbox] = useState(0)
  const nav = useNavigate()

  useEffect(() => {
    const onLogout = () => setUser(null)
    window.addEventListener('dg:logout', onLogout)
    if (getToken()) api.me().then(setUser).catch(() => setToken(null)).finally(() => setReady(true))
    else setReady(true)
    return () => window.removeEventListener('dg:logout', onLogout)
  }, [])

  useEffect(() => {
    if (!user) return
    const load = () => {
      api.health().then(setHealth).catch(() => setHealth(null))
      api.inbox().then(x => setInbox(x.length)).catch(() => {})
    }
    load()
    const t = setInterval(load, 30000)
    const refresh = () => api.inbox().then(x => setInbox(x.length)).catch(() => {})
    window.addEventListener('dg:inbox', refresh)
    return () => { clearInterval(t); window.removeEventListener('dg:inbox', refresh) }
  }, [user])

  if (!ready) return null
  if (!user) return <Login onLogin={(u) => { setUser(u); nav('/') }} />

  const logout = () => { setToken(null); setUser(null); nav('/') }
  const isAdmin = user.role === 'admin'

  return (
    <UserCtx.Provider value={user}>
      <div className="shell">
        <aside className="sidebar">
          <div className="side-brand">
            <Logo size={30} />
            <div><b>Deliverable Guard</b><span>AI 交付守門員</span></div>
          </div>
          <nav className="side-nav">
            <NavLink to="/" end><LayoutDashboard size={18} />總覽</NavLink>
            <NavLink to="/projects"><FolderKanban size={18} />專案</NavLink>
            <NavLink to="/inbox"><InboxIcon size={18} />待我簽核{inbox > 0 && <span className="side-badge">{inbox}</span>}</NavLink>
            {isAdmin && <div className="side-label">管理</div>}
            {isAdmin && <NavLink to="/workflows"><GitBranch size={18} />簽核流程</NavLink>}
            {isAdmin && <NavLink to="/users"><UsersIcon size={18} />使用者與權限</NavLink>}
            {isAdmin && <NavLink to="/audit"><ScrollText size={18} />稽核日誌</NavLink>}
          </nav>
          <div className="side-foot">
            <div className={`model-status ${health?.llm ? 'on' : 'off'}`}>
              <i />
              <div>
                <b>{health?.llm ? '語意模型已連線' : '僅規則模式'}</b>
                <span>{health?.llm ? '地端 LLM · 資料不出內網' : '語意模型未連線'}</span>
              </div>
            </div>
            <div className="me">
              <div className="avatar">{user.display_name.slice(0, 1)}</div>
              <div className="me-text"><b>{user.display_name}</b><span>{ROLE_LABEL[user.role]}</span></div>
              <button className="icon-btn" onClick={logout} title="登出" aria-label="登出"><LogOut size={17} /></button>
            </div>
          </div>
        </aside>
        <main className="content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/projects" element={<Projects />} />
            <Route path="/projects/:id/*" element={<ProjectView />} />
            <Route path="/inbox" element={<Inbox onChange={() => api.inbox().then(x => setInbox(x.length)).catch(() => {})} />} />
            {isAdmin && <Route path="/workflows" element={<Workflows />} />}
            {isAdmin && <Route path="/users" element={<Users />} />}
            {isAdmin && <Route path="/audit" element={<Audit />} />}
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        </main>
      </div>
    </UserCtx.Provider>
  )
}
