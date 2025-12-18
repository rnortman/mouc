#!/bin/bash
# Run Rust tests with proper Python library path
# Required because PyO3 links to libpython when not using extension-module feature

set -e

# Get Python library directory from uv environment
PYTHON_LIBDIR=$(uv run python -c "import sysconfig; print(sysconfig.get_config_var('LIBDIR'))")

export LD_LIBRARY_PATH="$PYTHON_LIBDIR:$LD_LIBRARY_PATH"
export PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1

cargo test --lib "$@"
