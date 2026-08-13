.PHONY: test test-backend test-quant test-brokers test-frontend test-ci lint clean

# Python interpreter: override with `make PYTHON=/path/to/python`
PYTHON ?= .venv/bin/python

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

lint:
	$(PYTHON) -m ruff check quant backend/app brokers shared tests backend/tests
	cd frontend && npx tsc --noEmit

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf htmlcov/ .coverage .pytest_cache/
