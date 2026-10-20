UV ?= uv

.PHONY: setup db dev migrate check

setup:
	$(UV) sync --locked --group dev --no-build
	$(MAKE) migrate

db:
	docker compose up -d --wait postgres

dev: db
	$(UV) run --locked --no-build uvicorn app.main:create_app --factory --reload --no-access-log

migrate: db
	$(UV) run --locked --no-build alembic upgrade head

check:
	$(UV) lock --check
	$(UV) run --locked --no-build ruff check .
	$(UV) run --locked --no-build ruff format --check .
	$(UV) run --locked --no-build pytest -m 'not integration'
