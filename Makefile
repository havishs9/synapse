PY ?= .venv/bin/python
NPM ?= npm
RUN ?=

.PHONY: setup dev test demo-data replay build-frontend screenshots build-procurement build-logs build-support snapshot-demo deploy

setup:            ## create the venv and install backend + frontend dependencies
	python3.12 -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r requirements-dev.txt
	cd frontend && $(NPM) ci

build-frontend:
	cd frontend && $(NPM) run build

dev: build-frontend   ## backend on :8000 serving the built UI (use `cd frontend && npm run dev` for hot reload on :5173)
	$(PY) -m uvicorn backend.main:app --port 8000 --reload --reload-dir backend

test:
	$(PY) -m pytest -q

demo-data:
	$(PY) scripts/demo_data.py

build-procurement:
	$(PY) -m backend.cli build procurement

build-logs:
	$(PY) -m backend.cli build hdfs_logs

build-support:
	$(PY) -m backend.cli build support_tickets

replay: build-frontend   ## make replay RUN=<run_id>: serve the recorded runs; builds replay instead of training
	APP_MODE=replay ARTIFACTS_DIR=./artifacts/demo RUNS_DIR=./artifacts/demo/runs $(PY) -m uvicorn backend.main:app --port 8000

snapshot-demo:    ## copy the demo specialists and recorded runs into the committed demo folders
	$(PY) scripts/snapshot_demo.py $(RUN)

screenshots:
	$(PY) scripts/screenshots.py

deploy:           ## create the Nebius Serverless endpoint (needs the nebius CLI, logged in)
	./deploy/serverless/deploy.sh
