.PHONY: install dev lint format typecheck test clean

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
install:
	python -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e ".[dev]"
	.venv/bin/pre-commit install

dev: install

# ---------------------------------------------------------------------------
# Code quality
# ---------------------------------------------------------------------------
lint:
	.venv/bin/ruff check src tests

format:
	.venv/bin/black src tests
	.venv/bin/ruff check --fix src tests

typecheck:
	.venv/bin/pyright

check: lint typecheck

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
test:
	.venv/bin/pytest tests/ -v

test-cov:
	.venv/bin/pytest tests/ -v --cov=src/qode --cov-report=html

# ---------------------------------------------------------------------------
# Pre-commit
# ---------------------------------------------------------------------------
pre-commit:
	.venv/bin/pre-commit run --all-files

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
audit:
	.venv/bin/pip-audit

# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------
clean:
	rm -rf .venv __pycache__ .pytest_cache .ruff_cache dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
