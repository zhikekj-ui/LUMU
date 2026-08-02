.PHONY: install test lint format run docker docker-logs clean

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

run:
	python run.py

docker:
	docker compose up -d --build

docker-logs:
	docker compose logs -f agent

clean:
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
