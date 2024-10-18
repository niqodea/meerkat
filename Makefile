install:
	poetry install

lint:
	ruff format; \
	ruff check --fix; \
	mypy .

test:
	pytest .
