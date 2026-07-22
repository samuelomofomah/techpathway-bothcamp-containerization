#!/bin/sh
set -e

python db_init.py || true

exec gunicorn --config gunicorn.conf.py wsgi:app