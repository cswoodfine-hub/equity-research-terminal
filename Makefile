# Equity research terminal.
PY := backend/.venv/bin/python

.PHONY: dev test refresh refresh-daily tearsheets tearsheets-all \
        history-export history-rebuild clean

dev:            ## start the API (8000) and the UI (8501)
	./run.sh

test:           ## run the full test suite
	cd backend && .venv/bin/python -m pytest tests/ -q

refresh:        ## pull every source for the whole universe (needs the API up)
	curl -s -X POST 'localhost:8000/refresh?scope=all' | $(PY) -m json.tool

refresh-daily:  ## run the scheduled refresh directly (no API needed); logs to logs/
	$(PY) backend/scheduled_refresh.py

tearsheets:     ## write tearsheets for LLY, BMY, MRK to exports/ (needs the API up)
	@for t in LLY BMY MRK; do \
	  curl -s -X POST localhost:8000/companies/$$t/tearsheet | $(PY) -m json.tool; \
	done

tearsheets-all: ## write a tearsheet for every company to exports/ (no API needed)
	$(PY) backend/tearsheet.py

history-export: ## dump the snapshot history to data/history/*.ndjson for commit
	$(PY) backend/history.py export

history-rebuild: ## rebuild the database from committed data/history/*.ndjson
	$(PY) backend/history.py rebuild

clean:          ## remove generated tearsheets
	rm -f exports/*.html
