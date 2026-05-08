.PHONY: test test-unit test-integration test-e2e test-coverage test-ci test-critical lint format clean

test:
	cd backendv2 && PYTHONPATH=. python -m pytest tests/ -v

test-unit:
	cd backendv2 && PYTHONPATH=. python -m pytest tests/unit/ -v --tb=short

test-integration:
	cd backendv2 && PYTHONPATH=. python -m pytest tests/integration/ -v --tb=short --timeout=300

test-e2e:
	cd backendv2 && PYTHONPATH=. python -m pytest tests/e2e/ -v --tb=short

test-coverage:
	cd backendv2 && PYTHONPATH=. python -m pytest tests/ --cov=app --cov-report=html --cov-report=term-missing

test-ci:
	cd backendv2 && PYTHONPATH=. python -m pytest tests/unit/ -v --tb=line
	cd backendv2 && PYTHONPATH=. python -m pytest tests/integration/ -v --tb=line --timeout=300

test-critical:
	cd backendv2 && PYTHONPATH=. python -m pytest tests/ -v -m "not live and not slow"

lint:
	cd backendv2 && ruff check app/ tests/

format:
	cd backendv2 && ruff format app/ tests/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf htmlcov/ .coverage .pytest_cache/
