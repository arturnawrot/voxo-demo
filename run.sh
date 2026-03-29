#!/usr/bin/env bash

set -o errexit
set -o pipefail

DOCKER_USERNAME=${1:-"arturnawrot"}
IMAGE_NAME="${DOCKER_USERNAME}/voxo-demo:latest"

# ---- config ----
# docker compose subcommand: exec (default) or run
DC="${DC:-exec}"

# pass a TTY only if stdout is a terminal
TTY=""
if [[ ! -t 1 ]]; then
  TTY="-T"
fi

# ---- internal wrapper ----
function _dc {
  docker compose "${DC}" ${TTY} "${@}"
}

# ---- service helpers ----
function api {
  _dc api "${@}"
}

function worker {
  _dc worker "${@}"
}

# ---- dev ----
function dev {
  docker compose up api worker nginx redis db --build --force-recreate -d
}

# ---- prod ----
function prod {
  docker compose -f docker-compose.production.yml up -d api worker nginx redis db
}

function prod_build_local {
  docker compose up api worker nginx redis db --build --force-recreate -d
}

function fetch_latest_image {
  git pull
  docker pull "${IMAGE_NAME}"
}

# ---- database / migrations ----
function migrate {
  api alembic upgrade head
}

function migrate_create {
  # Usage: ./run.sh migrate_create "your message"
  api alembic revision --autogenerate -m "${1:?Usage: ./run.sh migrate_create <message>}"
}

function migrate_downgrade {
  api alembic downgrade -1
}

# ---- python / package helpers ----
function python {
  api python "${@}"
}

function pip {
  api pip "${@}"
}

# ---- redis ----
function redis_cli {
  _dc redis redis-cli "${@}"
}

function redis_flush {
  _dc redis redis-cli FLUSHALL
}

# ---- logs ----
function logs {
  docker compose logs -f "${@}"
}

# ---- shell ----
function shell {
  api bash "${@}"
}

# ---- lint / format ----
function lint {
  api ruff check .
}

function format {
  api ruff format .
}

# ---- tests ----
function test {
  api pytest "${@}"
}

# ---- manual sync (useful for debugging) ----
function sync {
  api python -c "from app.sync import run_sync; import json; print(json.dumps(run_sync(), indent=2))"
}

# ---- help ----
function help {
  printf "%s <task> [args]\n\nTasks:\n" "${0}"
  compgen -A function | grep -v "^_" | cat -n
}

TIMEFORMAT=$'\nTask completed in %3lR'
time "${@:-help}"
