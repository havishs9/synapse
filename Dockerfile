# Main app: FastAPI backend + built frontend + shared specialist routes (fallback serving).
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt
COPY backend/ backend/
COPY config/ config/
COPY scripts/ scripts/
COPY artifacts/demo/ artifacts/demo/
COPY runs/ runs/
COPY --from=web /web/dist frontend/dist
ENV ARTIFACTS_DIR=./artifacts/demo RUNS_DIR=./runs
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
