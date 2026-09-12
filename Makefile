.PHONY: build up down logs test lint

build:
	docker compose build

up:
	docker compose up app

down:
	docker compose down

logs:
	docker compose logs -f app

test:
	docker compose run --rm app pytest

lint:
	docker compose run --rm app ruff check .
