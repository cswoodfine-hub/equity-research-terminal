# Equity research terminal.
PY := backend/.venv/bin/python

.PHONY: dev test verify hooks refresh refresh-daily tearsheets tearsheets-all \
        history-export history-rebuild clean

dev:            ## start the API (8000) and the UI (8501)
	./run.sh

test:           ## run the full test suite, including the network tests
	cd backend && .venv/bin/python -m pytest tests/ -q

# Safe before a commit or a push in a && chain, which `pytest | tail` is not: a
# pipeline reports the exit status of its LAST command, so piping pytest into tail to
# shorten the output throws the result away and the chain runs on regardless. That is
# how a push once went out over five errors. Here the status is captured before
# anything is piped anywhere, so the summary still prints and the exit code survives.
#
# test_refresh.py is left out: its ten tests go to the network and take four minutes
# against thirty-five seconds for the other 1,520, so gating every push on them would
# fail a push on a train. `make test` runs them.
verify:         ## fast suite with a real exit code; safe before a commit or a push
	@cd backend && .venv/bin/python -m pytest tests/ -q \
	  --ignore=tests/test_refresh.py > /tmp/er_verify.log 2>&1; \
	  status=$$?; tail -3 /tmp/er_verify.log; exit $$status

hooks:          ## install the pre-push hook (undo: git config --unset core.hooksPath)
	@git config core.hooksPath githooks
	@echo "pre-push hook installed; pushes now run make verify first"

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
