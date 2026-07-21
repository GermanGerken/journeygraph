PYTHON ?= python3
VENV := .venv
PY := $(VENV)/bin/python
RUFF := $(VENV)/bin/ruff
PYTEST := $(VENV)/bin/pytest
ENSURE_VENV_VISIBLE = if command -v chflags >/dev/null 2>&1; then chflags -R nohidden $(VENV); fi

.PHONY: setup format format-check lint typecheck test test-unit test-integration \
	test-functional coverage build wheel-smoke demo docs-check security mutation benchmark verify clean

setup:
	$(PYTHON) -m venv --clear $(VENV)
	@# Python ignores UF_HIDDEN .pth files; macOS can propagate that flag from a dot-directory.
	@$(ENSURE_VENV_VISIBLE)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -c requirements-dev.lock -e '.[dev,mutation,parquet]'
	@# A later pip operation can restore inherited flags, so clear them after installation too.
	@$(ENSURE_VENV_VISIBLE)

format:
	@$(ENSURE_VENV_VISIBLE)
	$(RUFF) format src tests_unit tests_integration tests_functional scripts
	$(RUFF) check --fix src tests_unit tests_integration tests_functional scripts

format-check:
	@$(ENSURE_VENV_VISIBLE)
	$(RUFF) format --check src tests_unit tests_integration tests_functional scripts

lint:
	@$(ENSURE_VENV_VISIBLE)
	$(RUFF) check src tests_unit tests_integration tests_functional scripts

typecheck:
	@$(ENSURE_VENV_VISIBLE)
	$(PY) -m mypy

test: test-unit test-integration test-functional

test-unit:
	@$(ENSURE_VENV_VISIBLE)
	$(PYTEST) tests_unit

test-integration:
	@$(ENSURE_VENV_VISIBLE)
	$(PYTEST) tests_integration

test-functional:
	@$(ENSURE_VENV_VISIBLE)
	$(PYTEST) tests_functional

coverage:
	@# Python ignores UF_HIDDEN .pth files, including the subprocess coverage hook.
	@$(ENSURE_VENV_VISIBLE)
	mkdir -p artifacts
	$(PYTEST) tests_unit tests_integration tests_functional --cov=journeygraph --cov-branch \
		--cov-report=term-missing --cov-report=xml:artifacts/coverage.xml --cov-fail-under=90 \
		--junitxml=artifacts/junit.xml

build:
	@$(ENSURE_VENV_VISIBLE)
	$(PY) -m build

wheel-smoke: build
	@$(ENSURE_VENV_VISIBLE)
	$(PY) scripts/verify_wheel.py

demo:
	@$(ENSURE_VENV_VISIBLE)
	$(VENV)/bin/journeygraph demo --output-dir artifacts/demo --force

docs-check:
	@$(ENSURE_VENV_VISIBLE)
	$(PY) scripts/check_docs.py

security:
	@$(ENSURE_VENV_VISIBLE)
	$(PY) -m pip_audit --local --skip-editable
	$(VENV)/bin/bandit -q -r src
	git ls-files --cached --others --exclude-standard -z | \
		xargs -0 $(VENV)/bin/detect-secrets-hook --no-verify --baseline .secrets.baseline

mutation:
	@$(ENSURE_VENV_VISIBLE)
	$(VENV)/bin/mutmut run
	@# mutmut can create environment files inheriting UF_HIDDEN from a macOS dot-directory.
	@$(ENSURE_VENV_VISIBLE)

benchmark:
	@$(ENSURE_VENV_VISIBLE)
	$(PY) scripts/benchmark.py --traces 2000 --steps 12

verify: format-check lint typecheck coverage wheel-smoke docs-check security

clean:
	$(PY) -c "from pathlib import Path; import shutil; [shutil.rmtree(p, ignore_errors=True) for p in map(Path, ('build', 'dist', 'htmlcov'))]"
