# Deliverable Guard｜AI 交付守門員

跨文件一致性與風險檢核 Agent（POC）。上傳同一專案的提案、報價、合約、規格書、簡報與會議紀錄，系統建立可追溯的**專案事實主檔**，以**規則引擎＋語意模型**偵測直接矛盾、遺漏與疑似過期資訊，產生**附原文證據的衝突清單**，由承辦人確認後匯出。

> 系統只標示差異並附原文證據，**不自動修改文件、不作法律判斷**。

## 架構

```
瀏覽器 (React)  ──►  FastAPI 後端 (本機)  ──SSH 通道──►  GCP VM：vLLM + Qwen3-32B-AWQ (A100)
                       │                                 只綁 127.0.0.1，不對外開 port
                       ├─ 解析：DOCX / PDF / XLSX / PPTX，掃描 PDF → OCR（RapidOCR）→ 依專案詞彙語意校正
                       ├─ 去識別化（人名、電話、Email、身分證、帳號）→ 可追溯段落（頁碼＋位置）
                       ├─ 文件分類、版本辨識（檔名／內容／中繼資料），版本分組，只比對最新版
                       ├─ 事實抽取：規則（欄位：值、品項表格）＋ LLM（引文必須逐字對回原段落，否則丟棄）
                       ├─ 品項名稱歸一（模糊比對＋LLM；同一文件內並列的品項不可合併）
                       ├─ 檢核：值不一致、大小寫金額、明細加總、遺漏、引用舊版、沿用舊版值、日期邏輯
                       ├─ 語意判定：規則無法決定的文字差異交 LLM 判斷同義／矛盾
                       └─ 帳號角色、機密分級、雙人覆核、保存期限、稽核日誌、XLSX/DOCX 匯出
```

| 提案項目 | 實作位置 |
|---|---|
| 多格式解析、OCR、版本辨識 | `backend/dg/parsing.py`、`versioning.py`、`engine.correct_ocr_segments` |
| 專案事實主檔、欄位字典 | `backend/dg/fields.py`、`extract_rules.py`、`extract_llm.py`、`engine.fact_master` |
| 規則檢核與語意比對 | `backend/dg/checks.py`、`extract_llm.judge_pairs` |
| 證據式警示（文件／頁面／原句） | 每項 Finding 的 `evidence`；引文保證為原段落逐字子字串 |
| 人工確認與匯出 | `api.py` 覆核（雙人一致即定案、意見不一 → 爭議，由覆核者最終裁定）、`export.py` |
| 去識別化、權限分級、唯讀、保存期限、稽核 | `deid.py`、`auth.py`、`ingest.py`（原檔 0440 唯讀＋SHA-256）、`retention.py`、`AuditLog` |
| 交付簽核（簽核節點） | `workflow.py`：送簽關卡、可設定節點範本（依角色／指定人員、金額門檻、含特定文件類型等條件）、快照與文件指紋、文件變動自動失效、職責分離、簽核單 DOCX；前端「交付簽核」分頁、「待我簽核」、「簽核流程」範本管理 |
| 模型地端化 | `infra/llm-vm/`（專用 VM，資料不出專案環境） |


## 部署

部署主機需求：Linux、Python 3.12 與 [uv](https://docs.astral.sh/uv/)、Node 20+（首次啟動建置前端）、gcloud CLI（連語意模型 VM 時）。

```bash
git clone <repo> deliverable-guard && cd deliverable-guard

# 1. 建立語意模型 VM（只需一次；A100，啟動腳本自動安裝 vLLM 並以 systemd 常駐）
#    會在 infra/llm-vm/ 產生 .api_key 與 .zone（不進版控）
infra/llm-vm/create_vm.sh

# 2. 啟動：開 SSH 通道 → 建置前端（frontend/dist 不存在時）→ 在 0.0.0.0:8000 提供網頁與 API
./run.sh
```

內網其他電腦以 `http://<主機IP>:8000` 連線；若有防火牆需開放 8000/tcp（例：`sudo ufw allow 8000/tcp`）。

首次啟動會建立 `admin` / `handler` / `reviewer` / `manager`（主管）/ `legal`（法務）帳號，隨機密碼寫在 `var/initial_passwords.txt`（權限 600），登入後請改密碼。

### 常駐（systemd）

```ini
# /etc/systemd/system/deliverable-guard.service
[Unit]
Description=Deliverable Guard
After=network-online.target

[Service]
User=<部署帳號>
WorkingDirectory=/opt/deliverable-guard
# uv、npm 所在路徑（systemd 不會載入使用者的 shell PATH）
Environment=PATH=/home/<部署帳號>/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/opt/deliverable-guard/run.sh
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now deliverable-guard
```

### 設定（環境變數）

| 變數 | 預設 | 說明 |
|---|---|---|
| `DG_DATA_DIR` | `var/` | 資料庫、原檔、匯出檔位置（請納入備份） |
| `DG_SECRET_KEY` | 自動產生並存於 `var/secret_key` | 登入權杖與簽核簽章用金鑰；多台部署時須一致 |
| `DG_HOST` | `0.0.0.0` | 只供本機使用時設 `127.0.0.1` |
| `DG_LLM_ENABLED` | `1` | `0` 為純規則模式（不需 VM，文字同義判斷改列低嚴重度待人工確認） |
| `DG_LLM_BASE_URL` / `DG_LLM_MODEL` / `DG_LLM_API_KEY` | 通道 `127.0.0.1:18000`、`dg-llm`、讀 `.api_key` | 改接其他 OpenAI 相容端點時設定 |
| `DG_LLM_CONCURRENCY` | `8` | 同時送給模型的請求數 |
| `DG_RETENTION_DAYS` | `180` | 專案資料預設保存天數 |
| `DG_MAX_UPLOAD_MB` | `50` | 單檔上傳上限 |
| `DG_OCR_REC_MODEL` / `DG_OCR_REC_KEYS` | `backend/models/` | OCR 文字辨識模型（預設 PP-OCRv5 server）與字典 |
| `DG_OPEN_LOGIN` | `0` | **僅限測試**：`1` 時任何帳密皆可登入，正式環境不可開啟 |

不用時關閉 VM 以免計費（再次使用前 `start`）：

```bash
~/google-cloud-sdk/bin/gcloud compute instances stop deliverable-guard-llm --zone "$(cat infra/llm-vm/.zone)"
```

## 驗證結果（POC，合成資料）

10 組去識別化合成文件包（業務接案、研發專案各 5 組，共 65 份文件、40 項植入衝突）：檢出率 100%（40/40）、誤報率 0%、證據率 100%，每包約 33 秒。掃描頁 OCR 字元錯誤率 1.83%。以上皆為合成資料結果，正式上線前需以真實（去識別化）文件驗證。
