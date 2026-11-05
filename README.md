# Deliverable Guard｜AI 交付守門員

跨文件一致性與風險檢核 Agent（POC）。上傳同一專案的提案、報價、合約、規格書、簡報與會議紀錄，系統建立可追溯的**專案事實主檔**，以**規則引擎＋語意模型**偵測直接矛盾、遺漏與疑似過期資訊，產生**附原文證據的衝突清單**，由承辦人確認後匯出。

> 系統只標示差異並附原文證據，**不自動修改文件、不作法律判斷**。

## 架構

```
瀏覽器 (React)  ──►  FastAPI 後端（本地伺服器 :8000）  ──OpenAI 相容 API──►  GPU 主機：vLLM + Qwen3-32B-AWQ
                       │                                                       （可與後端同一台，或內網另一台）
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
| 模型地端化 | 本地 GPU 主機以 vLLM 提供服務（資料不出內網）；`infra/llm-vm/` 為 GCP VM 的替代方案 |


## 部署（本地伺服器）

系統分兩個服務，可裝在同一台或分開兩台：

| 服務 | 主機需求 | 埠 |
|---|---|---|
| **語意模型**（vLLM + Qwen3-32B-AWQ） | Linux、NVIDIA GPU（實測 A100 40GB）、NVIDIA 驅動 | 8000（可自訂，例：8001） |
| **Deliverable Guard**（網頁＋API，含 OCR） | Linux x86_64、Python 3.12；不需要 GPU | 8000 |

同一台時請把語意模型改用其他埠（以下範例用 8001）。

### 1. 需要下載的項目與來源

| 項目 | 下載位置 | 大小 | 何時下載 |
|---|---|---|---|
| 本專案程式碼 | https://github.com/gino6178/guard | 約 75 MB | `git clone` |
| OCR 文字辨識模型（PP-OCRv5 server，已轉 ONNX） | **已包含在本 repo**：`backend/models/ocr_rec.onnx`、`ocr_rec_keys.txt` | 84 MB | 隨程式碼 |
| OCR 文字偵測／方向模型 | 包含在 Python 套件 `rapidocr-onnxruntime` 1.4.4 內（PyPI） | — | 隨 Python 套件 |
| 語意模型 Qwen3-32B-AWQ（Apache-2.0 授權） | Hugging Face：https://huggingface.co/Qwen/Qwen3-32B-AWQ | 19.3 GB（14 個檔案） | 部署語意模型時，見步驟 2 |
| vLLM（模型服務程式） | PyPI：https://pypi.org/project/vllm/ 或 Docker 映像 `vllm/vllm-openai`（https://hub.docker.com/r/vllm/vllm-openai） | 數 GB（含 PyTorch／CUDA） | 部署語意模型時 |
| 後端 Python 套件 | PyPI：https://pypi.org （版本鎖定於 `backend/uv.lock`） | 約 230 MB | 首次 `./run.sh`，或離線安裝時預先下載 |
| uv（Python 套件管理） | https://docs.astral.sh/uv/getting-started/installation/ （或 `pip install uv`） | 約 40 MB | 部署前；離線安裝可不用 |
| 前端 npm 套件 | npm：https://registry.npmjs.org （版本鎖定於 `frontend/package-lock.json`） | 約 100 MB | 首次 `./run.sh` 建置前端時；離線可改帶已建置的 `frontend/dist` |
| Node.js 20 以上 | https://nodejs.org | — | 只在建置前端時需要 |

執行期間**不需要連外**：OCR 模型、字型（前端內建 Noto Sans TC）都在本機，語意模型只在內網呼叫。

### 2. 語意模型服務（GPU 主機）

```bash
# 安裝 vLLM 與下載工具（需可連外；離線環境見下方「離線安裝」）
python3.12 -m venv /opt/dg-llm/venv
/opt/dg-llm/venv/bin/pip install "vllm>=0.10" huggingface_hub

# 下載模型到本機目錄（來源 https://huggingface.co/Qwen/Qwen3-32B-AWQ，19.3 GB）
/opt/dg-llm/venv/bin/hf download Qwen/Qwen3-32B-AWQ --local-dir /opt/dg-llm/models/Qwen3-32B-AWQ

# 自訂一組 API 金鑰，兩個服務要設成同一組
openssl rand -hex 24 > /opt/dg-llm/api_key

# 啟動（名稱必須是 dg-llm）
/opt/dg-llm/venv/bin/vllm serve /opt/dg-llm/models/Qwen3-32B-AWQ \
  --served-model-name dg-llm --host 0.0.0.0 --port 8001 \
  --api-key "$(cat /opt/dg-llm/api_key)" \
  --max-model-len 32768 --gpu-memory-utilization 0.92 --enable-prefix-caching
```

確認服務正常：

```bash
curl -H "Authorization: Bearer $(cat /opt/dg-llm/api_key)" http://<GPU主機IP>:8001/v1/models
```

顯示卡記憶體：模型權重約 19 GB，實測環境為 A100 40GB。24 GB 顯示卡可嘗試把 `--max-model-len` 降到 8192（未實測）。與後端同一台時把 `--host` 改成 `127.0.0.1`，不對內網開放。

### 3. Deliverable Guard（網頁＋API）

```bash
git clone https://github.com/gino6178/guard.git deliverable-guard && cd deliverable-guard

export DG_LLM_BASE_URL=http://<GPU主機IP>:8001/v1      # 同一台時用 http://127.0.0.1:8001/v1
export DG_LLM_API_KEY=<步驟 2 的 API 金鑰>

# 首次執行會用 uv 安裝 Python 套件、用 npm 建置前端，之後在 0.0.0.0:8000 提供網頁與 API
./run.sh
```

內網其他電腦以 `http://<主機IP>:8000` 連線；若有防火牆需開放 8000/tcp（例：`sudo ufw allow 8000/tcp`）。

首次啟動會建立 `admin` / `handler` / `reviewer` / `manager`（主管）/ `legal`（法務）帳號，隨機密碼寫在 `var/initial_passwords.txt`（權限 600），登入後請改密碼。

連不到語意模型時，系統仍可運作，但只用規則檢核（文字同義判斷改列低嚴重度待人工確認），網頁左側欄底部會顯示「語意模型已連線」或「僅規則模式」。

### 離線安裝（伺服器無法連外）

在一台**可連外**的 Linux x86_64 電腦準備好，再把整個資料夾複製到伺服器：

```bash
git clone https://github.com/gino6178/guard.git deliverable-guard && cd deliverable-guard

# 前端：先建置好，伺服器上就不需要 Node 與 npm
(cd frontend && npm ci && npm run build)

# 後端：下載所有 Python 套件（約 230 MB）到 backend/wheels/
cd backend
uv export --frozen --no-dev --no-hashes --no-emit-project -o requirements.txt
uv run --with pip --no-project python -m pip download -r requirements.txt -d wheels \
  --only-binary=:all: --python-version 3.12 \
  --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux_2_28_x86_64 --platform linux_x86_64
```

語意模型也在可連外的電腦先下載，再複製 `Qwen3-32B-AWQ/` 資料夾過去：`hf download Qwen/Qwen3-32B-AWQ --local-dir Qwen3-32B-AWQ`。vLLM 建議用 Docker 映像 `vllm/vllm-openai`：可連外時 `docker pull vllm/vllm-openai:<版本>`、`docker save` 存成檔案，在伺服器上 `docker load` 載入。

在伺服器上（需 Python 3.12，不需 uv）：

```bash
cd deliverable-guard/backend
python3.12 -m venv .venv
.venv/bin/pip install --no-index --find-links wheels -r requirements.txt
cd ..
DG_OFFLINE=1 DG_LLM_BASE_URL=http://<GPU主機IP>:8001/v1 DG_LLM_API_KEY=<金鑰> ./run.sh
```

`DG_OFFLINE=1` 會直接用 `backend/.venv` 啟動，不再連網安裝套件。

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
Environment=DG_LLM_BASE_URL=http://<GPU主機IP>:8001/v1
Environment=DG_LLM_API_KEY=<金鑰>
# 離線安裝時加上：Environment=DG_OFFLINE=1
ExecStart=/opt/deliverable-guard/run.sh
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

語意模型也可用同樣方式常駐：把 `ExecStart` 換成步驟 2 的 `vllm serve ...` 指令即可。

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now deliverable-guard
```

### 設定（環境變數）

| 變數 | 預設 | 說明 |
|---|---|---|
| `DG_LLM_BASE_URL` | `http://127.0.0.1:18000/v1` | 語意模型服務位址（OpenAI 相容 API） |
| `DG_LLM_API_KEY` | 讀 `infra/llm-vm/.api_key` | 語意模型服務的 API 金鑰 |
| `DG_LLM_MODEL` | `dg-llm` | 需與 vLLM 的 `--served-model-name` 相同 |
| `DG_LLM_ENABLED` | `1` | `0` 為純規則模式，不呼叫語意模型 |
| `DG_LLM_CONCURRENCY` | `8` | 同時送給模型的請求數 |
| `DG_OFFLINE` | `0` | `1` 時直接用已安裝的 `backend/.venv` 啟動（離線安裝用） |
| `DG_DATA_DIR` | `var/` | 資料庫、原檔、匯出檔位置（請納入備份） |
| `DG_SECRET_KEY` | 自動產生並存於 `var/secret_key` | 登入權杖與簽核簽章用金鑰；多台部署時須一致 |
| `DG_HOST` | `0.0.0.0` | 只供本機使用時設 `127.0.0.1` |
| `DG_RETENTION_DAYS` | `180` | 專案資料預設保存天數 |
| `DG_MAX_UPLOAD_MB` | `50` | 單檔上傳上限 |
| `DG_OCR_REC_MODEL` / `DG_OCR_REC_KEYS` | `backend/models/` | OCR 文字辨識模型（預設 PP-OCRv5 server）與字典 |
| `DG_OPEN_LOGIN` | `0` | **僅限測試**：`1` 時任何帳密皆可登入，正式環境不可開啟 |

### 附錄：改用 GCP VM 提供語意模型

沒有本地 GPU 時，`infra/llm-vm/create_vm.sh` 會在 GCP 建立 A100 VM、自動安裝 vLLM 並下載模型，產生 `infra/llm-vm/.api_key` 與 `.zone`；之後 `./run.sh` 會自動開 SSH 通道，不需設定 `DG_LLM_BASE_URL`。需要 gcloud CLI，VM 開機期間持續計費，不用時請停機：

```bash
~/google-cloud-sdk/bin/gcloud compute instances stop deliverable-guard-llm --zone "$(cat infra/llm-vm/.zone)"
```

## 驗證結果（POC，合成資料）

10 組去識別化合成文件包（業務接案、研發專案各 5 組，共 65 份文件、40 項植入衝突）：檢出率 100%（40/40）、誤報率 0%、證據率 100%，每包約 33 秒。掃描頁 OCR 字元錯誤率 1.83%。以上皆為合成資料結果，正式上線前需以真實（去識別化）文件驗證。
