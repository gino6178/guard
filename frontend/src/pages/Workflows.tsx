import { useEffect, useState } from 'react'
import { ArrowDown, ArrowUp, Plus, Save, Trash2 } from 'lucide-react'
import { api, type WfNode, type WfTemplate } from '../api'
import { DOC_TYPES } from '../util'

type Meta = { roles: Record<string, string>; conditions: Record<string, string>; users: { id: number; name: string; role: string }[] }
const blankNode = (): WfNode => ({ name: '新節點', assignee_type: 'role', role: 'manager', users: [], condition: { type: 'always' } })

export default function Workflows() {
  const [tpls, setTpls] = useState<WfTemplate[]>([])
  const [meta, setMeta] = useState<Meta | null>(null)
  const [sel, setSel] = useState<number | 'new' | null>(null)
  const [draft, setDraft] = useState<Omit<WfTemplate, 'id'> | null>(null)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const load = () => api.workflows().then(r => { setTpls(r.templates); setMeta(r); return r })
  useEffect(() => { load().then(r => r.templates[0] && pick(r.templates[0])) }, [])

  const pick = (t: WfTemplate) => { setSel(t.id); setDraft({ name: t.name, scenario: t.scenario, nodes: structuredClone(t.nodes), active: t.active }); setMsg(null) }
  const newTpl = () => { setSel('new'); setDraft({ name: '新簽核流程', scenario: '', nodes: [blankNode()], active: true }); setMsg(null) }

  const setNode = (i: number, patch: Partial<WfNode>) => setDraft(d => d && { ...d, nodes: d.nodes.map((n, k) => k === i ? { ...n, ...patch } : n) })
  const move = (i: number, dir: -1 | 1) => setDraft(d => {
    if (!d) return d
    const nodes = [...d.nodes]
    const j = i + dir
    if (j < 0 || j >= nodes.length) return d
    ;[nodes[i], nodes[j]] = [nodes[j], nodes[i]]
    return { ...d, nodes }
  })

  const save = async () => {
    if (!draft) return
    try {
      const t = sel === 'new' ? await api.createWorkflow(draft) : await api.updateWorkflow(sel as number, draft)
      await load(); pick(t); setMsg({ ok: true, text: '已儲存。新送簽的案件會套用新設定，進行中的簽核不受影響。' })
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }) }
  }

  if (!meta) return <div className="page"><div className="skeleton" /></div>

  return (
    <div className="page">
      <header className="page-header">
        <div><h1>簽核流程範本</h1><p className="muted">定義交付前要經過哪些關卡、由誰簽、在什麼條件下才需要簽。</p></div>
        <button className="btn primary" onClick={newTpl}><Plus size={16} />新增範本</button>
      </header>
      <div className="wf-layout">
        <ul className="card wf-list">
          {tpls.map(t => (
            <li key={t.id} className={sel === t.id ? 'on' : ''} onClick={() => pick(t)}>
              <b>{t.name}</b>
              <span className="muted small">{t.scenario === 'sales' ? '業務接案' : t.scenario === 'rnd' ? '研發專案' : '全部場景'} · {t.nodes.length} 個節點{!t.active && ' · 停用'}</span>
            </li>
          ))}
          {sel === 'new' && <li className="on"><b>（新範本）</b></li>}
        </ul>
        {draft && (
          <section className="card wf-editor">
            <div className="form-2">
              <label>範本名稱<input value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} /></label>
              <label>適用場景
                <select value={draft.scenario} onChange={e => setDraft({ ...draft, scenario: e.target.value })}>
                  <option value="">全部</option><option value="sales">業務接案</option><option value="rnd">研發專案</option>
                </select>
              </label>
            </div>
            <label className="check"><input type="checkbox" checked={draft.active} onChange={e => setDraft({ ...draft, active: e.target.checked })} />啟用</label>

            <div className="ev-head">節點（依序簽核）</div>
            <ol className="wf-nodes">
              {draft.nodes.map((n, i) => (
                <li key={i} className="wf-node">
                  <span className="wf-index">{i + 1}</span>
                  <div className="wf-fields">
                    <label>節點名稱<input value={n.name} onChange={e => setNode(i, { name: e.target.value })} /></label>
                    <label>簽核人
                      <div className="row nowrap-row">
                        <select value={n.assignee_type} onChange={e => setNode(i, { assignee_type: e.target.value as WfNode['assignee_type'] })}>
                          <option value="role">依角色</option><option value="users">指定人員</option>
                        </select>
                        {n.assignee_type === 'role' ? (
                          <select value={n.role} onChange={e => setNode(i, { role: e.target.value })}>
                            {Object.entries(meta.roles).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                          </select>
                        ) : (
                          <select multiple value={n.users.map(String)} onChange={e => setNode(i, { users: Array.from(e.target.selectedOptions).map(o => +o.value) })}>
                            {meta.users.map(u => <option key={u.id} value={u.id}>{u.name}（{meta.roles[u.role] ?? u.role}）</option>)}
                          </select>
                        )}
                      </div>
                    </label>
                    <label>需簽條件
                      <div className="row nowrap-row">
                        <select value={n.condition.type} onChange={e => setNode(i, { condition: { type: e.target.value as WfNode['condition']['type'], value: e.target.value === 'has_doc_type' ? 'contract' : e.target.value === 'amount_gte' ? 1000000 : undefined } })}>
                          {Object.entries(meta.conditions).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                        </select>
                        {n.condition.type === 'amount_gte' && <input type="number" step={100000} value={Number(n.condition.value ?? 0)} onChange={e => setNode(i, { condition: { ...n.condition, value: +e.target.value } })} />}
                        {n.condition.type === 'has_doc_type' && (
                          <select value={String(n.condition.value ?? 'contract')} onChange={e => setNode(i, { condition: { ...n.condition, value: e.target.value } })}>
                            {Object.entries(DOC_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                          </select>
                        )}
                      </div>
                    </label>
                  </div>
                  <div className="wf-actions">
                    <button className="icon-btn" onClick={() => move(i, -1)} disabled={i === 0} aria-label="上移"><ArrowUp size={16} /></button>
                    <button className="icon-btn" onClick={() => move(i, 1)} disabled={i === draft.nodes.length - 1} aria-label="下移"><ArrowDown size={16} /></button>
                    <button className="icon-btn" onClick={() => setDraft({ ...draft, nodes: draft.nodes.filter((_, k) => k !== i) })} disabled={draft.nodes.length === 1} aria-label="刪除"><Trash2 size={16} /></button>
                  </div>
                </li>
              ))}
            </ol>
            <button className="btn ghost" onClick={() => setDraft({ ...draft, nodes: [...draft.nodes, blankNode()] })}><Plus size={16} />新增節點</button>
            {msg && <div className={`alert ${msg.ok ? 'ok' : 'error'}`}>{msg.text}</div>}
            <div className="row end"><button className="btn primary" onClick={save}><Save size={16} />儲存範本</button></div>
            <p className="muted small">規則：送簽人不可簽自己的案件；同一人不可簽兩個關卡；條件不成立的節點自動免簽並記錄原因。</p>
          </section>
        )}
      </div>
    </div>
  )
}
