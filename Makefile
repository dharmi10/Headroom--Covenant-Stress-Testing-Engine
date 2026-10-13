# Headroom
#
# `make demo` is the one that matters: from a fresh clone it loads the golden
# deal through both approval gates and prints the run beside the independent
# hand calculation.

PY := .venv/Scripts/python.exe
ifeq (,$(wildcard .venv/Scripts/python.exe))
PY := .venv/bin/python
endif

.PHONY: help venv install test demo demo-live api ui golden fixture hand-calc measure clean

help:
	@echo "make install    create the virtualenv and install everything"
	@echo "make test       run the test suite"
	@echo "make demo       load the golden deal and run its quarter, offline"
	@echo "make demo-live  the same, fetching the agreement and facts from EDGAR"
	@echo "make api        start the backend on http://127.0.0.1:8000"
	@echo "make ui         start the frontend on http://localhost:5173"
	@echo "make golden     rebuild the hand-written golden formula from the agreement"
	@echo "make hand-calc  recompute expected.json independently of the evaluator"
	@echo "make measure    measure the compiler against the golden formula (needs credentials)"

venv:
	uv venv --python 3.11 .venv || python -m venv .venv

install: venv
	uv pip install --python $(PY) -e ".[dev]" || $(PY) -m pip install -e ".[dev]"
	cd frontend && npm install

test:
	$(PY) -m pytest -q

demo:
	$(PY) -m scripts.seed_golden

demo-live:
	$(PY) -m scripts.seed_golden --live

api:
	$(PY) -m uvicorn backend.api.main:app --reload --port 8000

ui:
	cd frontend && npm run dev

golden:
	$(PY) -m scripts.build_golden

fixture:
	$(PY) -m scripts.build_fixture

hand-calc:
	$(PY) -m scripts.hand_calc

measure:
	$(PY) -m scripts.measure_compiler

clean:
	rm -f headroom.db
	rm -rf frontend/dist .pytest_cache
