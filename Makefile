.PHONY: test test-backend test-quant test-brokers test-frontend test-ci lint clean parity

# Python interpreter: override with `make PYTHON=/path/to/python`
PYTHON ?= $(CURDIR)/.venv/bin/python

test: test-backend test-quant test-brokers test-frontend

test-backend:
	cd backend && PYTHONPATH=..:. $(PYTHON) -m pytest tests/ -q --no-header

test-quant:
	PYTHONPATH=backend:. $(PYTHON) -m pytest tests/ -q --no-header

test-brokers:
	cd brokers && PYTHONPATH=..:. $(PYTHON) -m pytest -q --no-header

test-frontend:
	cd frontend && npm test

# Fast CI pass: backend + quant unit/offline tests, brokers, frontend.
test-ci:
	cd backend && PYTHONPATH=..:. $(PYTHON) -m pytest tests/ -q --no-header -m "not slow and not live"
	PYTHONPATH=backend:. $(PYTHON) -m pytest tests/ -q --no-header -m "not slow and not live"
	cd brokers && PYTHONPATH=..:. $(PYTHON) -m pytest -q --no-header -m "not slow and not live"
	cd frontend && npm test

# Certification parity gate: golden suites + journal-replay determinism battery.
parity:
	PYTHONPATH=backend:. $(PYTHON) -m pytest tests/quant/test_golden_tape.py tests/quant/test_golden_replay.py tests/quant/test_golden_file.py tests/quant/certification/ -q --no-header
	PYTHONPATH=backend:. $(PYTHON) -m tests.quant.certification.run_battery --limit 5

lint:
	$(PYTHON) -m ruff check quant backend/app brokers shared tests backend/tests
	cd frontend && npx tsc --noEmit

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf htmlcov/ .coverage .pytest_cache/

test-arch:
	PYTHONPATH=backend:. $(PYTHON) -m pytest tests/architecture/ -v --no-header

test-fast:
	PYTHONPATH=backend:. $(PYTHON) -m pytest tests/quant/ tests/architecture/ -q --no-header -x

