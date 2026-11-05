import { Check, Circle, CornerUpLeft, Send, SkipForward } from 'lucide-react'
import type { Approval, ResolvedNode } from '../api'

type NodeState = 'done' | 'current' | 'pending' | 'skipped' | 'rejected'

function nodeStates(nodes: ResolvedNode[], a?: Approval): NodeState[] {
  return nodes.map((n, i) => {
    if (n.skipped) return 'skipped'
    if (!a) return 'pending'
    const acted = a.steps.filter(s => s.node_index === i && s.action !== 'comment')
    const last = acted[acted.length - 1]
    if (last?.action === 'approve') return 'done'
    if (last?.action === 'reject') return 'rejected'
    if (a.status === 'in_progress' && a.current === i) return 'current'
    return 'pending'
  })
}

/** Horizontal sign-off flow: 送簽 → node → node → 可交付. */
export default function Flow({ nodes, approval, submitter }: { nodes: ResolvedNode[]; approval?: Approval; submitter?: string }) {
  const states = nodeStates(nodes, approval)
  const finished = approval?.status === 'approved'
  return (
    <ol className="flow">
      <li className="flow-node done start">
        <span className="flow-dot"><Send size={14} /></span>
        <div className="flow-text"><b>送簽</b><span>{submitter ?? '承辦人'}</span></div>
      </li>
      {nodes.map((n, i) => {
        const st = states[i]
        const step = approval?.steps.filter(s => s.node_index === i && s.action !== 'comment').slice(-1)[0]
        return (
          <li key={i} className={`flow-node ${st}`}>
            <span className="flow-dot">
              {st === 'done' ? <Check size={14} /> : st === 'rejected' ? <CornerUpLeft size={14} /> : st === 'skipped' ? <SkipForward size={14} /> : <Circle size={10} />}
            </span>
            <div className="flow-text">
              <b>{n.name}</b>
              <span>{st === 'skipped' ? `免簽：${n.reason}` : step ? `${step.user} · ${new Date(step.at).toLocaleDateString('zh-TW')}` : n.assignee_label}</span>
              {st === 'current' && <em>等待簽核</em>}
              {st !== 'skipped' && n.condition?.type !== 'always' && !step && <small>{n.reason}</small>}
            </div>
          </li>
        )
      })}
      <li className={`flow-node end ${finished ? 'done' : 'pending'}`}>
        <span className="flow-dot"><Check size={14} /></span>
        <div className="flow-text"><b>可對外交付</b><span>{finished ? new Date(approval!.completed_at!).toLocaleDateString('zh-TW') : '全部核准後'}</span></div>
      </li>
    </ol>
  )
}
