PYFILES = $(wildcard *.py)
check:
	ruff check $(PYFILES)
	mypy $(PYFILES)
	pyright $(PYFILES)

build:
	rm -rf dist
	uv build

upload: build
	uv-publish

doc:
	update-readme-usage -A

format:
	ruff check --select I --fix $(PYFILES) && ruff format $(PYFILES)

clean:
	@rm -vrf *.egg-info build/ dist/ __pycache__
