.PHONY: lint format type help

.DEFAULT_GOAL := help

.EXPORT_ALL_VARIABLES:
UV_FROZEN = true

######################
# LINTING AND FORMATTING
######################

PYTHON_FILES=.
lint format: PYTHON_FILES=.
lint_diff format_diff: PYTHON_FILES=$(shell git diff --relative=libs/partners/teel --name-only --diff-filter=d main | grep -E '\.py$$|\.ipynb$$')
lint_package: ## Lint only the package
lint_package: PYTHON_FILES=langchain_teel

lint: ## Run linters and type checker
lint lint_diff lint_package:
	[ "$(PYTHON_FILES)" = "" ] || uv run --all-groups ruff check $(PYTHON_FILES)
	[ "$(PYTHON_FILES)" = "" ] || uv run --all-groups ruff format $(PYTHON_FILES) --diff
	$(MAKE) type

type: ## Run type checker
type typecheck:
	uv run --all-groups ty check langchain_teel

format: ## Run code formatters
format format_diff:
	[ "$(PYTHON_FILES)" = "" ] || uv run --all-groups ruff format $(PYTHON_FILES)
	[ "$(PYTHON_FILES)" = "" ] || uv run --all-groups ruff check --fix $(PYTHON_FILES)

######################
# HELP
######################

help: ## Show this help message
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
