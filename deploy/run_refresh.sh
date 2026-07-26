#!/bin/bash
# launchd entry point for the 06:00 daily refresh.
#
# The project lives under ~/Documents, which macOS protects with TCC, so a launchd
# background job cannot read the repo, the .env or the database until it is granted
# Full Disk Access. The grant is given to /bin/bash (this script's interpreter and the
# job's responsible process); the python it launches below inherits that access, so
# only one binary has to be authorised. Do not use `exec` here: bash must stay the
# parent so it remains the process the grant applies to.
#
# Grant it once in System Settings, Privacy & Security, Full Disk Access: add /bin/bash
# (press Cmd+Shift+G in the file picker and enter /bin/bash), then turn it on.
cd "/Users/charleswoodfine/Documents/WORK/Projects/ER Tool" || exit 1
"backend/.venv/bin/python" "backend/scheduled_refresh.py"
