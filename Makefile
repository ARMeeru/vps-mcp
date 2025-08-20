# MCP VPS Manager - Development Makefile

.PHONY: help install install-dev test lint format clean build package upload docs

# Default target
help:
	@echo "MCP VPS Manager - Available commands:"
	@echo "  install       Install package in development mode"
	@echo "  install-dev   Install with development dependencies"
	@echo "  test          Run tests"
	@echo "  lint          Run linting (flake8, mypy)"
	@echo "  format        Format code (black, isort)"
	@echo "  clean         Clean build artifacts"
	@echo "  build         Build distribution packages"
	@echo "  package       Create distribution packages"
	@echo "  upload        Upload to PyPI (requires credentials)"
	@echo "  docs          Generate documentation"
	@echo "  check         Run all checks (lint + test)"

# Installation targets
install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"

install-poetry:
	poetry install

# Development targets
test:
	pytest tests/ -v

lint:
	flake8 src/ tests/
	mypy src/

format:
	black src/ tests/
	isort src/ tests/

# Build targets
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

build: clean
	python setup.py sdist bdist_wheel

package: clean
	poetry build

# Upload targets (use with caution)
upload-test:
	twine upload --repository testpypi dist/*

upload:
	twine upload dist/*

# Quality checks
check: lint test

# Documentation
docs:
	@echo "Documentation available in:"
	@echo "  - README.md (Project overview)"
	@echo "  - INSTALL.md (Installation guide)"
	@echo "  - templates/ (Configuration templates)"

# Development server
dev-server:
	python bin/mcp-vps-manager --config config/servers.yaml --log-level DEBUG

# Package verification
verify-package:
	python setup.py check --strict --metadata
	twine check dist/*
