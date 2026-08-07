#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
work_root="$repo_root/test-data/work/opentelemetry-demo"
raw_root="$repo_root/test-data/raw/otel-demo"
raw_file="$raw_root/traces.jsonl"
collector_compose="$repo_root/test-data/collector/compose.yaml"
override="$repo_root/test-data/collector/demo-override.yaml"
client_venv="$repo_root/test-data/.venv-demo-client"
generated_proto="$raw_root/generated-proto"
project=journeygraph-otel-demo
pin_env="$repo_root/test-data/work/harness-pins.env"

"$repo_root/.venv/bin/python" "$repo_root/scripts/trace_corpus.py" write-pin-env \
  --output "$pin_env" >/dev/null
. "$pin_env"

mkdir -p "$(dirname -- "$work_root")" "$raw_root"
if [ ! -d "$work_root/.git" ]; then
  git clone --filter=blob:none https://github.com/open-telemetry/opentelemetry-demo.git "$work_root"
fi
git -C "$work_root" fetch --quiet origin "$OTEL_DEMO_COMMIT"
git -C "$work_root" checkout --quiet --detach "$OTEL_DEMO_COMMIT"
test "$(git -C "$work_root" rev-parse HEAD)" = "$OTEL_DEMO_COMMIT"

python3 -m venv "$client_venv"
"$client_venv/bin/python" -m pip install --disable-pip-version-check --quiet \
  -r "$repo_root/test-data/opentelemetry-demo/requirements.lock"
mkdir -p "$generated_proto"
"$client_venv/bin/python" -m grpc_tools.protoc \
  -I "$work_root/pb" \
  --python_out "$generated_proto" \
  --grpc_python_out "$generated_proto" \
  "$work_root/pb/demo.proto"

docker compose --env-file "$pin_env" -f "$collector_compose" down
rm -f "$raw_file"

export JOURNEYGRAPH_CAPTURE_DURATION="30s"
export JOURNEYGRAPH_COLLECTOR_CONFIG="$repo_root/test-data/collector/config.yaml"
export JOURNEYGRAPH_FLAG_CONFIG="$work_root/src/flagd/demo.flagd.json"
export JOURNEYGRAPH_RAW_DIR="$raw_root"

compose() {
  docker compose --env-file "$work_root/.env" --env-file "$work_root/.env.override" \
    --env-file "$pin_env" --project-name "$project" \
    -f "$work_root/compose.yaml" -f "$override" "$@"
}
cleanup() {
  compose down --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

images=$(compose config --format json | "$repo_root/.venv/bin/python" -c '
import json, sys
config = json.load(sys.stdin)
services = config["services"]
needed = set()
def visit(name):
    if name in needed:
        return
    needed.add(name)
    depends = services[name].get("depends_on", {})
    for dependency in depends:
        visit(dependency)
visit("checkout")
visit("quote")
for image in sorted({services[name]["image"] for name in needed}):
    print(image)
')
for image in $images; do
  attempt=1
  until docker pull "$image"; do
    if [ "$attempt" -ge 4 ]; then
      echo "failed to pull pinned Demo dependency after 4 attempts: $image" >&2
      exit 1
    fi
    attempt=$((attempt + 1))
    sleep 2
  done
done

compose up -d --wait --no-build --pull never checkout quote
cart_port=$(docker port cart 7070/tcp | head -1 | sed 's/.*://')
checkout_port=$(docker port checkout 5050/tcp | head -1 | sed 's/.*://')
if ! "$client_venv/bin/python" "$repo_root/test-data/opentelemetry-demo/checkout_client.py" \
  --proto-dir "$generated_proto" \
  --cart-endpoint "127.0.0.1:$cart_port" \
  --checkout-endpoint "127.0.0.1:$checkout_port"; then
  compose logs --no-color email checkout payment shipping >"$raw_root/service-failure.log"
  echo "Demo client failed; service diagnostics saved in ignored raw storage" >&2
  exit 1
fi
sleep 5
compose stop otel-collector
test -s "$raw_file"

"$repo_root/.venv/bin/python" "$repo_root/scripts/trace_corpus.py" prepare \
  --input "$raw_file" \
  --output "$repo_root/test-data/fixtures/integration/otel-demo-3.0.0.otlp.json" \
  --provenance-template "$repo_root/test-data/opentelemetry-demo/provenance-template.json" \
  --max-traces 5
