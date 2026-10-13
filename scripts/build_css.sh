#!/bin/sh
# Build app/static/css/tailwind.css with the Tailwind standalone CLI (no Node needed).
#   scripts/build_css.sh           build once, minified (commit the result)
#   scripts/build_css.sh --watch   rebuild while you edit templates
# The pinned binary is downloaded once into .cache/ and checked against its sha256.
# The Dockerfile runs the same build, so production never ships a stale file.
set -eu
cd "$(dirname "$0")/.."

VERSION=3.4.17
case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)  ASSET=tailwindcss-linux-x64;   SHA=7d24f7fa191d2193b78cd5f5a42a6093e14409521908529f42d80b11fde1f1d4 ;;
  Linux-aarch64) ASSET=tailwindcss-linux-arm64; SHA=69b1378b8133192d7d2feb12a116fa12d035594f58db3eff215879e4ad8cf39b ;;
  Darwin-arm64)  ASSET=tailwindcss-macos-arm64; SHA=a1d0c7985759accca0bf12e51ac1dcbf0f6cf2fffb62e6e0f62d091c477a10a3 ;;
  Darwin-x86_64) ASSET=tailwindcss-macos-x64;   SHA=6cbdad74be776c087ffa5e9a057512c54898f9fe8828d3362212dfe32fc933a3 ;;
  *) echo "No Tailwind binary configured for $(uname -s)-$(uname -m)" >&2; exit 1 ;;
esac

BIN=".cache/tailwindcss-$VERSION-$ASSET"
if [ ! -x "$BIN" ]; then
  mkdir -p .cache
  curl -fsSL -o "$BIN.tmp" "https://github.com/tailwindlabs/tailwindcss/releases/download/v$VERSION/$ASSET"
  if command -v sha256sum >/dev/null; then sum=$(sha256sum "$BIN.tmp"); else sum=$(shasum -a 256 "$BIN.tmp"); fi
  [ "${sum%% *}" = "$SHA" ] || { echo "Checksum mismatch for $ASSET" >&2; rm -f "$BIN.tmp"; exit 1; }
  chmod +x "$BIN.tmp" && mv "$BIN.tmp" "$BIN"
fi

ARGS="-c tailwind.config.js -i app/static/css/tailwind.input.css -o app/static/css/tailwind.css"
if [ "${1:-}" = "--watch" ]; then
  exec "$BIN" $ARGS --watch
fi
exec "$BIN" $ARGS --minify
