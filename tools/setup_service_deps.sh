#!/usr/bin/env bash
# Fetch the minimal Sony service-runtime dependencies used by fx30_burst.py and
# fx30_pixel_shift.py, and verify that they import.
#
# Source: QAQLeonard/a7c2-fl23-research (src/camera_runtime): transport.py,
# core.py, compat.py, macos_host.py and vendor/pmca.  Only that subtree is
# sparse-checked out.  The result lives in the gitignored deps/ directory, which
# is already the default search path in fx30_burst.py.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPS="$ROOT/deps"
CLONE="$DEPS/a7c2-fl23-research"
SRC="$CLONE/src/camera_runtime"
REPO="https://github.com/QAQLeonard/a7c2-fl23-research.git"

mkdir -p "$DEPS"

if [ ! -d "$CLONE/.git" ]; then
  echo "Cloning service runtime metadata into $CLONE ..."
  git clone --depth 1 --filter=blob:none --sparse "$REPO" "$CLONE"
fi

echo "Checking out only src/camera_runtime runtime files ..."
git -C "$CLONE" sparse-checkout set --no-cone \
  /src/camera_runtime/transport.py \
  /src/camera_runtime/core.py \
  /src/camera_runtime/compat.py \
  /src/camera_runtime/macos_host.py \
  /src/camera_runtime/vendor/pmca

for f in transport.py core.py compat.py macos_host.py; do
  cp "$SRC/$f" "$DEPS/$f"
done
rm -rf "$DEPS/vendor"
cp -R "$SRC/vendor" "$DEPS/vendor"

PY="$ROOT/venv/bin/python"
if [ -x "$PY" ]; then
  echo "Installing Python USB dependencies into $ROOT/venv ..."
  "$PY" -m pip install -q pyusb libusb-package pycryptodomex pyyaml
else
  echo "No repo venv found at $ROOT/venv."
  echo "Install pyusb, libusb-package, pycryptodomex and pyyaml into the"
  echo "interpreter you use to run the tools, then re-run this script."
fi

echo "Verifying imports ..."
cd "$ROOT"
if [ -x "$PY" ]; then
  "$PY" - "$DEPS" <<'PY'
import sys
deps = sys.argv[1]
sys.path[:0] = [deps, deps + "/vendor"]
import transport  # noqa: F401
from pmca.usb.driver.generic import GenericUsbDriver  # noqa: F401
from pmca.usb.sony import SonySenserAuthDevice, SonySenserDevice  # noqa: F401
print("service runtime import OK:", transport.__file__)
PY
else
  echo "Skipped import check (no venv)."
fi

cat <<EOF

Service runtime ready in:
  $DEPS

The tools find it automatically through fx30_burst.py's default deps/ path.
Run with the repo venv, for example:
  $ROOT/venv/bin/python tools/fx30_pixel_shift.py --probe

macOS still needs sudo for USB access:
  sudo -E $ROOT/venv/bin/python tools/fx30_pixel_shift.py --probe
EOF
