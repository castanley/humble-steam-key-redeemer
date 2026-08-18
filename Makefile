.PHONY: run install sync test clean help

help:
	@echo "Available commands:"
	@echo "  make run     - Run the humble-steam-redeem script"
	@echo "  make install - Install dependencies with uv"
	@echo "  make sync    - Sync lock file with pyproject.toml"
	@echo "  make test    - Run smoke tests"
	@echo "  make clean   - Remove generated files and cache"

run:
	uv run humble-steam-redeem

install:
	uv sync

sync:
	uv sync

test:
	uv run python smoke_test.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -f .coverage
