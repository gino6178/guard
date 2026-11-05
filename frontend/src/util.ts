export const fmtNT = (n: number) => `NT$${n.toLocaleString('en-US')}`
export const DOC_TYPES: Record<string, string> = {
  contract: '合約', quotation: '報價單', proposal: '提案書', spec: '規格書', sow: '工作說明書',
  acceptance: '驗收清單', slides: '簡報', minutes: '會議紀錄',
}
