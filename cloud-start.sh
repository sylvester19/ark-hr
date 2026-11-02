#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  git curl ca-certificates libreoffice-writer \
  tesseract-ocr tesseract-ocr-eng tesseract-ocr-fra tesseract-ocr-ara tesseract-ocr-por \
  xz-utils
curl -fsSL https://nodejs.org/dist/v22.17.0/node-v22.17.0-linux-x64.tar.gz \
  | tar -xz -C /usr/local --strip-components=1
rm -rf /opt/ark-hr
git clone --depth 1 https://github.com/sylvester19/ark-hr.git /opt/ark-hr
mkdir -p /opt/ark-hr/data/models
if [ -n "${ARK_HR_GROQ_API_KEY:-}" ]; then
  grep -v '^llama-cpp-python' /opt/ark-hr/requirements.txt > /tmp/ark-hr-req.txt
  python -m pip install --no-cache-dir -r /tmp/ark-hr-req.txt
else
  python -m pip install --no-cache-dir -r /opt/ark-hr/requirements.txt \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
  curl -fsSL -o /opt/ark-hr/data/models/qwen2.5-1.5b-instruct-q4_k_m.gguf \
    https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf
  export ARK_HR_GGUF=/opt/ark-hr/data/models/qwen2.5-1.5b-instruct-q4_k_m.gguf
fi
cd /opt/ark-hr/web
npm ci
npm run build
mkdir -p /opt/ark-hr/web-run/.next
cp -a .next/standalone/. /opt/ark-hr/web-run/
cp -a .next/static /opt/ark-hr/web-run/.next/static
cp -a public /opt/ark-hr/web-run/public
export PYTHONPATH=/opt/ark-hr/src
export ARK_HR_DATA_DIR=/opt/ark-hr/data
cd /opt/ark-hr
python -m ark_hr.api &
api=$!
cd /opt/ark-hr/web-run
PORT=3215 HOSTNAME=0.0.0.0 node server.js &
web=$!
trap 'kill $api $web 2>/dev/null' TERM INT
wait -n
kill $api $web 2>/dev/null
wait
