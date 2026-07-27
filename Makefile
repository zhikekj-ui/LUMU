.PHONY: install test lint format docker run

install:
	pip install -r requirements.txt

test:
	pytest tests/ -v

lint:
	black --check .
	ruff check .

format:
	black .
	ruff check . --fix

docker:
	docker-compose up --build

run:
	python run.py
