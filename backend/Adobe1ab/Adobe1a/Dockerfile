# Explicitly target amd64
FROM --platform=linux/amd64 python:3.10-slim

# ----- Proxy wiring (optional; safe if unset) -----
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    NO_PROXY=${NO_PROXY} \
    http_proxy=${HTTP_PROXY} \
    https_proxy=${HTTPS_PROXY} \
    no_proxy=${NO_PROXY} \
    A1A_ENABLE_OCR=0 \
    A1A_PAGE_BASE=1

# Let apt use the proxy if provided
RUN set -eux; \
    if [ -n "$HTTP_PROXY" ]; then echo "Acquire::http::Proxy \"$HTTP_PROXY\";"  > /etc/apt/apt.conf.d/99proxy; fi; \
    if [ -n "$HTTPS_PROXY" ]; then echo "Acquire::https::Proxy \"$HTTPS_PROXY\";" >> /etc/apt/apt.conf.d/99proxy; fi

# ----- System deps (OCR + PDF) -----
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        tesseract-ocr \
        tesseract-ocr-eng \
        libglib2.0-0 \
        libgl1 \
        libpoppler-cpp-dev \
        poppler-utils && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better layer caching)
COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Default entrypoint
CMD ["python", "main.py"]
