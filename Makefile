.DEFAULT_GOAL := help
.PHONY: help install validate lint format test check probe http tls clean

VENV   := .venv
PYTHON := $(VENV)/bin/python
PIP    := $(VENV)/bin/pip
RUFF   := $(VENV)/bin/ruff
PYTEST := $(VENV)/bin/pytest

help: ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "};{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

$(VENV): requirements-dev.txt
	python3 -m venv $(VENV)
	$(PIP) install --quiet --disable-pip-version-check -r requirements-dev.txt
	@touch $(VENV)

install: $(VENV) ## Create the dev virtualenv

validate: $(VENV) ## Validate .upptimerc.yml
	$(PYTHON) .github/scripts/validate_config.py

lint: $(VENV) ## Lint and check formatting
	$(RUFF) check .
	$(RUFF) format --check .

format: $(VENV) ## Autoformat and autofix
	$(RUFF) check --fix .
	$(RUFF) format .

test: $(VENV) ## Run the test suite
	$(PYTEST)

check: lint test validate ## Everything CI runs

probe: $(VENV) ## Probe every monitored target from this machine
	$(PYTHON) .github/scripts/probe.py

http: $(VENV) ## Probe only the HTTP endpoints
	$(PYTHON) .github/scripts/probe.py --http

tls: $(VENV) ## Show TLS certificate expiry
	$(PYTHON) .github/scripts/probe.py --tls

clean: ## Remove local build and tooling artifacts
	rm -rf $(VENV) .pytest_cache .ruff_cache site
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
