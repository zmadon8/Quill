#!/usr/bin/env bash
# Build step used by Render for both the website and the nightly backup job.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
