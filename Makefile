.PHONY: help app demo walkthrough test eval baseline check clean install

help:
	@echo "make app          browser UI at localhost:8000  <- start here"
	@echo "make demo         four demo scenarios in the terminal"
	@echo "make walkthrough  the same pipeline as a marketer sees it"
	@echo "make test      unit tests for the deterministic layer"
	@echo "make eval      full eval suite"
	@echo "make check     eval + regression check against baseline (CI target)"
	@echo "make baseline  record current eval scores as the floor"
	@echo "make install   optional production deps (needs network)"

app:
	@python3 -m src.webapp

demo:
	@python3 -m src.cli demo

walkthrough:
	@python3 -m src.walkthrough

test:
	@python3 -m unittest discover tests

eval:
	@python3 evals/run.py

baseline:
	@python3 evals/run.py --baseline

check: test
	@python3 evals/run.py --check

install:
	pip install anthropic pydantic slack-bolt pytest
	npm install -g mjml

clean:
	rm -rf traces/*.json out/ email_agent.db __pycache__ */__pycache__ */*/__pycache__
