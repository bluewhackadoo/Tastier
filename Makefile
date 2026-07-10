.PHONY: run check test test-e2e

run:
	uvicorn app.main:app --host 127.0.0.1 --port 8420

check:
	@python -c "import asyncio, json; from app.main import setup_validate; \
	print(json.dumps(asyncio.run(setup_validate()), indent=2))"

test:
	pytest tests/ -v --ignore=tests/test_e2e_paper.py

test-e2e:
	pytest tests/test_e2e_paper.py -v -s
