check:
	ruff check *.py
	flake8 *.py
	mypy *.py
	pyright *.py
	vermin -vv --no-tips -i *.py

build:
	rm -rf dist
	python3 -m build

upload: build
	uv-publish

doc:
	update-readme-usage -A

clean:
	@rm -vrf *.egg-info build/ dist/ __pycache__
