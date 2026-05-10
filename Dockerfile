# syntax=docker/dockerfile:1.6
#
# excella shorts-cutter — multi-stage Dockerfile.
#
# Stage 1 (kernel-builder): собирает _kernel.pyx → _kernel.cpython-*.so для Linux.
#                           ИСХОДНИК .pyx остаётся в этом слое — НЕ попадает в final.
# Stage 2 (runtime):        production-образ. Копирует только готовый .so из builder
#                           + основной src/, web/, branding/_assets/, vendor/LR-ASD/.
#
# Build:  docker build -t excella/shorts-cutter:dev .
# Run:    docker run --rm -p 8000:8000 -v $PWD/jobs:/app/jobs excella/shorts-cutter:dev
#
# Размер итогового образа: ~3.5 GB (PyTorch + opencv + faster-whisper модели lazy).
# Первый старт: ~30 секунд на загрузку модели MediaPipe (если нет volume cache).

# ────────────────────────────────────────────────────────────────────────
# Stage 1: builder — компилируем Cython kernel
# ────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS kernel-builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir setuptools cython==3.2.* cryptography==48.*

# Копируем ТОЛЬКО minimum для сборки kernel — .pyx + setup.py.
# .pyx содержит публичный ключ (вписан tools/make_keys.py до build).
# Master secret — XOR-фрагменты внутри .pyx (Phase 2 #15).
COPY brand_kernel_poc/brand_kernel/_kernel.pyx /build/brand_kernel/_kernel.pyx
COPY brand_kernel_poc/brand_kernel/__init__.py /build/brand_kernel/__init__.py
COPY brand_kernel_poc/setup.py /build/setup.py

RUN python setup.py build_ext --inplace \
    && ls -la /build/brand_kernel/

# ────────────────────────────────────────────────────────────────────────
# Stage 2: runtime — production-образ
# ────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Системные зависимости только для runtime: ffmpeg + opencv-headless GL stub.
# build-essential НЕ нужен в final image (.so уже собран в builder).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Python-зависимости.
COPY requirements.txt .
# opencv-python заменим на headless (без GUI) для меньшего размера.
RUN sed -i 's/opencv-python/opencv-python-headless/' requirements.txt && \
    pip install -r requirements.txt && \
    pip install python_speech_features  # для LR-ASD MFCC

# Копируем основные модули.
COPY src/ ./src/
COPY web/ ./web/
COPY scripts/ ./scripts/
COPY yolo26n.pt ./yolo26n.pt

# Brand-папка пустая — конкретный бренд приходит через volume mount
# от клиента (~/.excella/assets/* — расшифровываются brand_kernel'ом)
# или через docker-compose volume `./branding:/app/branding`.
# В image НЕ должно быть OAuth токенов или открытого excella.json.
RUN mkdir -p ./branding/_assets ./branding/_oauth

# LR-ASD vendor (13 MB, для активного спикера)
COPY vendor/LR-ASD/ ./vendor/LR-ASD/

# brand_kernel: только готовый .so из builder + __init__.py.
# ВНИМАНИЕ: .pyx исходник НЕ копируется в final — он остался в stage 1.
COPY --from=kernel-builder /build/brand_kernel/__init__.py ./vendor/brand_kernel/__init__.py
COPY --from=kernel-builder /build/brand_kernel/_kernel.cpython-312-*-linux-gnu.so ./vendor/brand_kernel/

# Job dirs — будут смонтированы как volume но создаём на случай ad-hoc.
RUN mkdir -p /app/jobs /app/downloads /app/output /app/.excella

# Регистрируем PYTHONPATH чтобы `from brand_kernel import ...` работал из src/branding.py.
ENV PYTHONPATH=/app/vendor

# uvicorn слушает 8000.
EXPOSE 8000

# Health-check: проверяем /jobs (legkий endpoint без побочных эффектов).
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/jobs > /dev/null || exit 1

CMD ["python", "-m", "uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"]
