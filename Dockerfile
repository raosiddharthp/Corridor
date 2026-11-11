FROM python:3.11-slim AS builder
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080
RUN useradd --create-home --uid 10001 corridor
WORKDIR /app
COPY --from=builder /install /usr/local
COPY app ./app
COPY pipeline ./pipeline
COPY supplier ./supplier
USER corridor
CMD ["sh", "-c", "if [ \"$SERVICE\" = supplier ]; then exec uvicorn supplier.main:build --factory --host 0.0.0.0 --port \"$PORT\"; else exec uvicorn app.main:app --host 0.0.0.0 --port \"$PORT\"; fi"]
