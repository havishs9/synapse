# Synapse image: the API endpoint (shared specialist server + build dispatcher) and the build workers (Nebius AI
# Jobs). Built and pushed by .github/workflows/image.yml to Nebius Container Registry (docs/TEAM_PLAN.md §2.4).
#   endpoint: default CMD (uvicorn on :8000)
#   worker:   python -m backend.builds.worker <run_id>
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 DEBIAN_FRONTEND=noninteractive \
    NEBIUS_CLI=/root/.nebius/bin/nebius HF_HOME=/opt/hf
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends libgomp1 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first, so code-only changes rebuild in seconds.
WORKDIR /app
COPY requirements.txt .
RUN pip install -q torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install -q -r requirements.txt
# Local embedding model for candidate C, so workers don't download it on every build.
RUN python -c "from sentence_transformers import SentenceTransformer as S; S('sentence-transformers/all-MiniLM-L6-v2')"
# nebius CLI: the endpoint's dispatcher launches worker jobs with it.
RUN curl -sSL https://artifacts.nebius.cloud/cli/install.sh | bash && "$NEBIUS_CLI" version

COPY . .
ARG GIT_SHA=unknown
ENV SYNAPSE_GIT_SHA=$GIT_SHA
EXPOSE 8000
ENTRYPOINT ["bash", "/app/deploy/image/entrypoint.sh"]
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
