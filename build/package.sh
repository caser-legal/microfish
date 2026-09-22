#!/bin/bash
# Assembles MicroFish.app from the translated project source.
#
# Usage:  package.sh [PROJECT_DIR]
#
# Inputs:
#   PROJECT_DIR/build/appsrc/launcher.swift   (Swift launcher source)
#   PROJECT_DIR/build/appsrc/Info.plist        (bundle metadata)
#   PROJECT_DIR/serve_dist.py                  (runtime UI server)
#   PROJECT_DIR/frontend/dist                  (pre-built UI, produced by `npm run build`)
#   PROJECT_DIR/frontend/public/icon.png       (app icon source)
#
# Output:
#   PROJECT_DIR/build/MicroFish.app
set -euo pipefail

PROJECT_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
BUILD_DIR="$PROJECT_DIR/build"
APPSRC="$BUILD_DIR/appsrc"
APP="$BUILD_DIR/MicroFish.app"
CONTENTS="$APP/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"

echo "==> Packaging MicroFish.app"
echo "    project: $PROJECT_DIR"

if [ ! -f "$PROJECT_DIR/frontend/dist/index.html" ]; then
    echo "ERROR: frontend/dist/index.html not found. Run 'npm run build' in frontend/ first." >&2
    exit 1
fi
if [ ! -f "$PROJECT_DIR/serve_dist.py" ]; then
    echo "ERROR: serve_dist.py not found at project root." >&2
    exit 1
fi

rm -rf "$APP"
mkdir -p "$MACOS" "$RESOURCES"

echo "==> Copying translated source (with pre-built UI) into Resources/microfish-src"
mkdir -p "$RESOURCES/microfish-src"
# bsdtar on macOS supports --exclude; copies everything except heavy/generated/local paths.
( cd "$PROJECT_DIR" && tar \
    --exclude='node_modules' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='build' \
    --exclude='logs' \
    --exclude='uploads' \
    --exclude='.git' \
    --exclude='.DS_Store' \
    -cf - . ) | ( cd "$RESOURCES/microfish-src" && tar -xf - )

echo "==> Compiling Swift launcher (Xcode toolchain)"
swiftc -O "$APPSRC/launcher.swift" -o "$MACOS/MicroFish" -framework Cocoa

echo "==> Installing Info.plist"
cp "$APPSRC/Info.plist" "$CONTENTS/Info.plist"

echo "==> Building app icon"
ICON_SRC="$PROJECT_DIR/frontend/public/icon.png"
if [ ! -f "$ICON_SRC" ]; then
    ICON_SRC="$PROJECT_DIR/static/image/MicroFish_logo.jpeg"
fi
ICONSET="$BUILD_DIR/AppIcon.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
make_icon() { sips -z "$2" "$2" "$ICON_SRC" --out "$1" >/dev/null 2>&1 || true; }
make_icon "$ICONSET/icon_16x16.png" 16
make_icon "$ICONSET/icon_16x16@2x.png" 32
make_icon "$ICONSET/icon_32x32.png" 32
make_icon "$ICONSET/icon_32x32@2x.png" 64
make_icon "$ICONSET/icon_128x128.png" 128
make_icon "$ICONSET/icon_128x128@2x.png" 256
make_icon "$ICONSET/icon_256x256.png" 256
make_icon "$ICONSET/icon_256x256@2x.png" 512
make_icon "$ICONSET/icon_512x512.png" 512
make_icon "$ICONSET/icon_512x512@2x.png" 1024
if iconutil -c icns "$ICONSET" -o "$RESOURCES/AppIcon.icns" >/dev/null 2>&1; then
    echo "    icon built"
else
    echo "    WARNING: icon build failed; continuing without icon"
fi

echo "==> Ad-hoc codesign"
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || echo "    WARNING: codesign failed (app still runs locally)"

echo "==> Verifying bundle"
test -f "$MACOS/MicroFish" && echo "    OK: MacOS/MicroFish"
test -f "$CONTENTS/Info.plist" && echo "    OK: Info.plist"
test -f "$RESOURCES/microfish-src/backend/run.py" && echo "    OK: bundled backend"
test -f "$RESOURCES/microfish-src/frontend/dist/index.html" && echo "    OK: bundled UI"

echo "==> Built: $APP"
