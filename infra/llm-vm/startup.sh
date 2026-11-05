#!/bin/bash
# GCE startup script: installs vLLM and serves an OpenAI-compatible API on 127.0.0.1 only.
# The API is never exposed publicly; clients reach it through an SSH tunnel (see tunnel.sh).
set -euxo pipefail

MODEL="$(curl -s -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/attributes/dg-model || echo Qwen/Qwen3-32B-AWQ)"
API_KEY="$(curl -s -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/attributes/dg-api-key)"
MAX_LEN="$(curl -s -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/attributes/dg-max-len || echo 32768)"

install -d -m 755 /opt/dg
if [ ! -x /opt/dg/venv/bin/ninja ]; then
  apt-get update -y && apt-get install -y python3-venv
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
  /usr/local/bin/uv venv --python 3.12 /opt/dg/venv
  VIRTUAL_ENV=/opt/dg/venv /usr/local/bin/uv pip install "vllm>=0.10" huggingface_hub ninja
fi

cat > /etc/systemd/system/dg-vllm.service <<EOF
[Unit]
Description=Deliverable Guard vLLM server
After=network-online.target

[Service]
Environment=HF_HOME=/opt/dg/hf
Environment=PATH=/opt/dg/venv/bin:/usr/local/cuda/bin:/usr/local/bin:/usr/bin:/bin
Environment=VLLM_API_KEY=${API_KEY}
ExecStart=/opt/dg/venv/bin/vllm serve ${MODEL} \\
  --host 127.0.0.1 --port 8000 \\
  --served-model-name dg-llm \\
  --max-model-len ${MAX_LEN} \\
  --gpu-memory-utilization 0.92 \\
  --enable-prefix-caching
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now dg-vllm.service
