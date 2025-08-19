# =========================
# 1) FRONTEND BUILD (CRA)
# =========================
FROM node:20-alpine AS frontend
WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --include=dev

COPY frontend/ ./
ENV DISABLE_ESLINT_PLUGIN=true
RUN npm run build  # -> /app/frontend/build

# =========================
# 2) BACKEND RUNTIME
# =========================
FROM python:3.12-bookworm
WORKDIR /app

# --- System deps (OCR + local TTS) ---
RUN set -eux; \
  for i in 1 2 3; do \
    apt-get update && \
    apt-get install -y --no-install-recommends \
      tesseract-ocr \
      espeak-ng \
      espeak \
      ffmpeg \
    && break || (echo "apt failed, retry $i/3" && sleep 6); \
  done; \
  rm -rf /var/lib/apt/lists/*

# Make ffmpeg/ffprobe obvious to pydub
RUN ln -sf /usr/bin/ffmpeg  /usr/local/bin/ffmpeg && \
    ln -sf /usr/bin/ffprobe /usr/local/bin/ffprobe
ENV PATH="/usr/bin:${PATH}" \
    FFMPEG_BINARY=/usr/bin/ffmpeg \
    FFPROBE_BINARY=/usr/bin/ffprobe

# --- App files ---
COPY backend/ ./backend/

# Create runtime folders to avoid FileNotFoundError
RUN mkdir -p \
    backend/Adobe_1A/input \
    backend/Adobe_1A/output \
    backend/Adobe_1B/data \
    backend/Adobe_1B/output \
    backend/podcast

# Serve the built frontend from Flask
COPY --from=frontend /app/frontend/build ./frontend_dist

# --- Python deps ---
ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
COPY backend/requirements.txt ./backend/requirements.txt
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r backend/requirements.txt

# --- Defaults (override with -e) ---
ENV PYTHONUNBUFFERED=1 \
    LLM_PROVIDER=gemini \
    GEMINI_MODEL=gemini-2.5-flash \
    TTS_PROVIDER=auto

EXPOSE 8080
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8080", "backend.controller_app:app"]
