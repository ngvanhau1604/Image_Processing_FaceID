.PHONY: test lint run setup models simulator

test:
	python -m pytest -q

lint:
	python -m ruff check .

run:
	python scripts/run_web.py

setup:
	python -m smartdoor.setup

models:
	python -m smartdoor.models

simulator:
	python -m smartdoor.simulator
