UV ?= uv

.PHONY: setup db storage dev migrate seed-exercises check

setup:
	$(UV) sync --locked --group dev --no-build
	$(MAKE) migrate

db:
	docker compose up -d --wait postgres

storage:
	docker compose up -d --wait azurite

dev: db storage
	$(UV) run --locked --no-build uvicorn app.main:create_app --factory --reload --no-access-log

seed-exercises: storage migrate
	$(UV) run --locked --no-build python -m app.features.training.seed --dataset "$(DATASET)"

migrate: db
	$(UV) run --locked --no-build alembic upgrade head

check:
	$(UV) lock --check
	$(UV) run --locked --no-build ruff check .
	$(UV) run --locked --no-build ruff format --check .
	$(UV) run --locked --no-build pytest -m 'not integration'
