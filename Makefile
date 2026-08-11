SHELL := /bin/bash
COMPOSE := docker compose -f docker-compose.test.yml
TEST_DATABASE_URL := postgresql+psycopg://marketevolver_test:marketevolver_test_only@127.0.0.1:55432/marketevolver_test

.PHONY: postgres-up postgres-down test-offline test-postgres test-all validate validate-live

postgres-up:
	$(COMPOSE) up -d --wait postgres-test

postgres-down:
	$(COMPOSE) down --volumes --remove-orphans

test-offline:
	.venv/bin/pytest -m "not postgres and not live and not external_provider"

test-postgres:
	MARKET_EVOLVER_TEST_POSTGRES_URL=$(TEST_DATABASE_URL) .venv/bin/pytest -m postgres

test-all: test-offline test-postgres

validate:
	MARKET_EVOLVER_TEST_POSTGRES_URL=$(TEST_DATABASE_URL) .venv/bin/market-evolver validate-system

validate-live: postgres-up
	@test "$(LIVE)" = "YES" || (echo "Set LIVE=YES to explicitly permit bounded external requests"; exit 2)
	MARKET_EVOLVER_DATABASE_URL=$(TEST_DATABASE_URL) .venv/bin/alembic upgrade head
	MARKET_EVOLVER_TEST_POSTGRES_URL=$(TEST_DATABASE_URL) .venv/bin/market-evolver validate-live --confirm-live
