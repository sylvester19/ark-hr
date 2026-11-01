FROM node:22-bookworm-slim AS web
WORKDIR /src
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    libreoffice-writer \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-fra \
    tesseract-ocr-ara \
    tesseract-ocr-por \
    xz-utils \
    && curl -fsSL https://nodejs.org/dist/v22.17.0/node-v22.17.0-linux-x64.tar.gz \
      | tar -xz -C /usr/local --strip-components=1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
COPY src ./src
COPY pytest.ini .
COPY start.sh /app/start.sh
COPY --from=web /src/.next/standalone /app/web
COPY --from=web /src/.next/static /app/web/.next/static
COPY --from=web /src/public /app/web/public
RUN mkdir -p /app/data/models \
    && curl -fsSL -o /app/data/models/qwen2.5-1.5b-instruct-q4_k_m.gguf \
      https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf \
    && chmod +x /app/start.sh

ENV PYTHONPATH=/app/src
ENV ARK_HR_ENV=prod
ENV ARK_HR_PHASE=1
ENV ARK_HR_DATA_DIR=/app/data
ENV ARK_HR_GGUF=/app/data/models/qwen2.5-1.5b-instruct-q4_k_m.gguf
EXPOSE 3215
CMD ["/bin/bash", "/app/start.sh"]
