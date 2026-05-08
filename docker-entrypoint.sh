#!/bin/sh
set -e

cd /app
mkdir -p /app/data

exec "$@"
