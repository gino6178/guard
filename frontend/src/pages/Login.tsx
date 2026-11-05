import { useEffect, useState, type FormEvent } from 'react'
import { FileSearch, Lock, ShieldCheck } from 'lucide-react'
import { api, setToken, type User } from '../api'
import { Logo } from '../components/ui'

export default function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(false)
  useEffect(() => { api.health().then(h => setOpen(!!h.open_login)).catch(() => {}) }, [])

  const signIn = async (u: string, pw: string) => {
    setBusy(true); setErr('')
    try {
      const r = await api.login(u, pw)
      setToken(r.token)
      onLogin(r.user)
    } catch (e) {
      setErr((e as Error).message)
    } finally { setBusy(false) }
  }
  const submit = (e: FormEvent) => { e.preventDefault(); signIn(username || 'admin', password || 'x') }

  return (
    <div className="login">
      <section className="login-hero">
        <div className="hero-brand"><Logo size={40} /><span>Deliverable Guard</span></div>
        <h1>文件送出前，<br />先讓 AI 交叉比對一次。</h1>
        <p>上傳同一專案的提案、報價、合約、規格書、簡報與會議紀錄，系統建立專案事實主檔，找出客戶名稱、金額、日期、數量、規格與版本的不一致，每一項都附原文證據。</p>
        <ul>
          <li><FileSearch size={18} />跨 DOCX、PDF、XLSX、PPTX 與掃描檔比對</li>
          <li><ShieldCheck size={18} />每項警示附文件、頁碼與原句，由承辦人確認</li>
          <li><Lock size={18} />地端語意模型、去識別化、權限分級與稽核日誌</li>
        </ul>
        <div className="hero-grid" aria-hidden />
      </section>
      <section className="login-panel">
        <form onSubmit={submit}>
          <h2>登入</h2>
          <p className="muted">使用內網帳號登入系統</p>
          {open && (
            <div className="test-mode">
              <b>測試模式</b>：任何帳號密碼皆可登入（未知帳號以管理員身分登入）。快速登入：
              <div className="row">
                <button type="button" className="btn ghost sm" onClick={() => signIn('admin', 'x')}>管理員</button>
                <button type="button" className="btn ghost sm" onClick={() => signIn('handler', 'x')}>承辦人</button>
                <button type="button" className="btn ghost sm" onClick={() => signIn('reviewer', 'x')}>覆核者</button>
                <button type="button" className="btn ghost sm" onClick={() => signIn('manager', 'x')}>主管</button>
                <button type="button" className="btn ghost sm" onClick={() => signIn('legal', 'x')}>法務</button>
              </div>
            </div>
          )}
          <label>帳號<input value={username} onChange={e => setUsername(e.target.value)} autoFocus autoComplete="username" /></label>
          <label>密碼<input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" /></label>
          {err && <div className="alert error">{err}</div>}
          <button className="btn primary lg" disabled={busy || (!open && (!username || !password))}>{busy ? '登入中…' : '登入'}</button>
          <p className="fine">系統僅標示差異並附原文證據，不自動修改文件、不作法律判斷。</p>
        </form>
      </section>
    </div>
  )
}
