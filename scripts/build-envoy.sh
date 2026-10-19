#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
source_dir=${ENVOY_SOURCE:-$root/build/envoy}
flags=()
if [[ $(uname -s) == Darwin ]]; then
  flags+=(--macos_minimum_os=13.0 --host_macos_minimum_os=13.0
    --copt=-mmacosx-version-min=13.0 --host_copt=-mmacosx-version-min=13.0
    --linkopt=-mmacosx-version-min=13.0 --host_linkopt=-mmacosx-version-min=13.0)
  if [[ $(uname -m) == arm64 ]]; then
    flags+=('--linkopt=-Wl,-exported_symbol,_envoy_dynamic_module_callback_*')
  fi
fi
# The pinned Envoy revision selects its hermetic Clang toolchain by default on Linux.
cd "$source_dir"
bazel build --jobs="${BUILD_JOBS:-6}" -c opt --define=no_debug_info=1 --fission=no \
  --override_repository="+envoy_build_config_ext+envoy_build_config=$root/envoy-build" \
  "${flags[@]}" //source/exe:envoy-static
install -m 755 bazel-bin/source/exe/envoy-static "$root/build/envoy-static"
