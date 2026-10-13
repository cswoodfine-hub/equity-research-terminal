#!/bin/bash
# launchd entry point for the 06:00 daily refresh.
#
# The project lives in ~/Projects, outside the folders macOS protects with TCC and
# outside iCloud Drive, so the job needs no Full Disk Access grant. Should it ever move
# back under ~/Documents, /bin/bash needs that grant again (System Settings, Privacy &
# Security, Full Disk Access), and bash must stay the parent here, so do not use `exec`.
cd "/Users/charleswoodfine/Projects/ER Tool" || exit 1
"backend/.venv/bin/python" "backend/scheduled_refresh.py"
