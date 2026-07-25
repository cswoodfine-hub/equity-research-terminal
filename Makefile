# Equity research terminal.
PY := backend/.venv/bin/python

.PHONY: dev test refresh tearsheets clean

dev:            ## start the API (8000) and the UI (8501)
	./run.sh

test:           ## run the full test suite
	cd backend && .venv/bin/python -m pytest tests/ -q

refresh:        ## pull every source for the whole universe
	curl -s -X POST 'localhost:8000/refresh?scope=all' | $(PY) -m json.tool

tearsheets:     ## write one-page tearsheets for LLY, BMY, MRK to exports/
	@for t in LLY BMY MRK; do \
	  curl -s -X POST localhost:8000/companies/$$t/tearsheet | $(PY) -m json.tool; \
	done

clean:          ## remove generated tearsheets
	rm -f exports/*.html
