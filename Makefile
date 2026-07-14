.PHONY: run check test test-e2e build

run:
	uvicorn app.main:app --host 127.0.0.1 --port 8420

build:
	pip install -r requirements-build.txt
	# stdlib distutils: setuptools' _distutils_hack asserts inside
	# PyInstaller's isolated child process otherwise (Python <= 3.11)
	SETUPTOOLS_USE_DISTUTILS=stdlib pyinstaller Tastier.spec --noconfirm

check:
	@python -c "import asyncio, json; from app.main import setup_validate; \
	print(json.dumps(asyncio.run(setup_validate()), indent=2))"

test:
	pytest tests/ -v --ignore=tests/test_e2e_paper.py

test-e2e:
	pytest tests/test_e2e_paper.py -v -s
