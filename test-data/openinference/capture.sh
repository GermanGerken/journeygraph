#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
venv="$repo_root/test-data/.venv-openinference"
raw_file="$repo_root/test-data/raw/traces.jsonl"
compose_file="$repo_root/test-data/collector/compose.yaml"
pin_env="$repo_root/test-data/work/harness-pins.env"
"$repo_root/.venv/bin/python" "$repo_root/scripts/trace_corpus.py" write-pin-env \
  --output "$pin_env" >/dev/null
compose() {
  docker compose --env-file "$pin_env" -f "$compose_file" "$@"
}
cleanup() {
  compose down >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

python3 -m venv "$venv"
"$venv/bin/python" -m pip install --disable-pip-version-check --quiet \
  -r "$repo_root/test-data/openinference/requirements.lock"
compose down
rm -f "$raw_file"
mkdir -p "$(dirname -- "$raw_file")"
compose up -d --wait
"$venv/bin/python" "$repo_root/test-data/openinference/generate.py"
compose stop collector

deadline=20
while [ ! -s "$raw_file" ] && [ "$deadline" -gt 0 ]; do
  sleep 1
  deadline=$((deadline - 1))
done
test -s "$raw_file"
"$repo_root/.venv/bin/python" "$repo_root/scripts/trace_corpus.py" prepare \
  --input "$raw_file" \
  --output "$repo_root/test-data/fixtures/integration/openinference-scenarios.otlp.json" \
  --provenance-template "$repo_root/test-data/openinference/provenance-template.json"
