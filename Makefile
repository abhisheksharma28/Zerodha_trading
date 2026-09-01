.PHONY: help up down build logs backend-shell frontend-shell migrate revision \
        test lint fmt typecheck seed sync-instruments reset-db

help:
	@echo "Common developer commands:"
	@echo "  make up              - start full stack (docker compose)"
	@echo "  make down            - stop full stack"
	@echo "  make build           - rebuild containers"
	@echo "  make logs            - tail all logs"
	@echo "  make migrate         - apply alembic migrations"
	@echo "  make revision m=msg  - create a new alembic revision (autogenerate)"
	@echo "  make test            - run backend test suite"
	@echo "  make lint            - ruff check backend"
	@echo "  make fmt             - ruff format backend"
	@echo "  make typecheck       - mypy backend"
	@echo "  make seed            - seed the strategy library (idempotent)"
	@echo "  make sync-instruments - refresh the NSE/NFO instrument master from Zerodha"
	@echo "  make reset-db        - drop and recreate the dev database (destructive)"

up:
	docker compose up --build

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

backend-shell:
	docker compose exec backend bash

frontend-shell:
	docker compose exec frontend sh

migrate:
	docker compose exec backend alembic upgrade head

revision:
	docker compose exec backend alembic revision --autogenerate -m "$(m)"

test:
	docker compose exec backend pytest -v

lint:
	docker compose exec backend ruff check .

fmt:
	docker compose exec backend ruff format .

typecheck:
	docker compose exec backend mypy app

seed:
	docker compose exec backend python -m app.seed

sync-instruments:
	docker compose exec backend python -m app.sync_instruments

reset-db:
	docker compose down -v
	docker compose up -d db redis
	sleep 3
	docker compose run --rm backend alembic upgrade head
