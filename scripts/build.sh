#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
export GOWORK=off
mkdir -p build
cp go.mod build/local.mod
if [[ -f go.sum ]]; then cp go.sum build/local.sum; fi
source_dir=${ENVOY_SOURCE:-$root/build/envoy}
go mod edit -modfile=build/local.mod \
  -replace="github.com/envoyproxy/envoy/source/extensions/dynamic_modules=$source_dir/source/extensions/dynamic_modules"
go mod tidy -modfile=build/local.mod
CGO_ENABLED=1 go build -modfile=build/local.mod -buildmode=c-shared \
  -o build/libattempt_policy.so ./cmd/module
go test -modfile=build/local.mod ./internal/...
