test:
	python -m pytest tests/

lint:
	ruff check .

clean:
	rm -rf __pycache__