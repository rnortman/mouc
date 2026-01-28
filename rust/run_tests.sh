#!/bin/bash
# Run Rust tests with proper Python configuration
# Required because PyO3 links to libpython when not using extension-module feature

set -e

# Configure PyO3 to use the uv-managed Python
export PYO3_PYTHON=$(uv run python -c "import sys; print(sys.executable)")
export PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1

# Set library path for linking
PYTHON_LIBDIR=$(uv run python -c "import sysconfig; print(sysconfig.get_config_var('LIBDIR'))")
export LD_LIBRARY_PATH="$PYTHON_LIBDIR:$LD_LIBRARY_PATH"

cargo test --lib "$@"
