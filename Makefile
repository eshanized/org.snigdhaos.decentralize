# Snigdha OS Decentralized - Mirror Automation Makefile
# SPDX-License-Identifier: GPL-3.0-or-later

PYTHON ?= python3
PYTEST ?= pytest

.PHONY: help install test lint stats clean

help:
	@echo "Available targets:"
	@echo "  install    Install release-mirror package in editable mode"
	@echo "  test       Run unit and integration test suite"
	@echo "  stats      Update public stats.json and badges"
	@echo "  lint       Run code formatting and syntax checks"
	@echo "  clean      Clean temporary build and cache artifacts"

install:
	$(PYTHON) -m pip install -e .

test:
	$(PYTEST) -v tests/

lint:
	$(PYTHON) -m py_compile release_mirror/*.py tests/*.py
	@echo "Syntax check passed."

stats:
	./bin/release-mirror stats --badges-dir public/badges --output public/stats.json

clean:
	rm -rf __pycache__ release_mirror/__pycache__ tests/__pycache__ *.egg-info .pytest_cache
