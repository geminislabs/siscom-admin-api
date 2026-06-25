#!/usr/bin/env bash

set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
	cp .env.example .env
	echo "Created .env from .env.example (adjust secrets before running)"
fi

bash scripts/setup.sh

echo ""
echo "Dev container ready."
echo "  Postgres/Kafka are external services — point .env to your instances."
echo "  Run: make run-dev"
