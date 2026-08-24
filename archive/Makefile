.PHONY: test test-backend test-quant test-brokers test-system test-unit test-integration test-coverage test-ci test-critical lint format clean

PYTHON ?= python3
PYTEST ?= $(PYTHON) -m pytest
PYTHONPATH := backend:.

# Run the complete repository suite. Live/network tests are expected to skip
# when credentials or market data are unavailable.
test:
	PYTHONPATH=$(PYTHONPATH) $(PYTEST) -q tests backend/tests brokers/tests

test-backend:
	PYTHONPATH=$(PYTHONPATH) $(PYTEST) -q backend/tests

test-quant:
	PYTHONPATH=$(PYTHONPATH) $(PYTEST) -q tests/quant tests/system

test-brokers:
	PYTHONPATH=$(PYTHONPATH) $(PYTEST) -q brokers/tests

test-system:
	PYTHONPATH=$(PYTHONPATH) $(PYTEST) -q tests/system backend/tests/integration

test-unit:
	PYTHONPATH=$(PYTHONPATH) $(PYTEST) -q backend/tests/unit tests/quant brokers/tests

test-integration:
	PYTHONPATH=$(PYTHONPATH) $(PYTEST) -q backend/tests/integration tests/system brokers/tests

test-coverage:
	PYTHONPATH=$(PYTHONPATH) $(PYTEST) -q tests backend/tests brokers/tests --cov=backend/app --cov=quant --cov=brokers --cov-report=term-missing --cov-report=xml

test-ci:
	PYTHONPATH=$(PYTHONPATH) $(PYTEST) -q backend/tests/unit tests/quant brokers/tests
	PYTHONPATH=$(PYTHONPATH) $(PYTEST) -q backend/tests/integration tests/system brokers/tests --timeout=300

test-critical:
	PYTHONPATH=$(PYTHONPATH) $(PYTEST) -q tests backend/tests brokers/tests -m "not live and not slow"

lint:
	ruff check backend/app quant brokers shared tests backend/tests brokers/tests

format:
	ruff format backend/app quant brokers shared tests backend/tests brokers/tests

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf htmlcov/ .coverage .pytest_cache/
