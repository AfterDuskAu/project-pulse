#!/bin/zsh
# Builds Pulse.app into the ProjectPulse folder (next to pulse.py, which it runs).
#   ./build-app.sh           Release build (what you double-click)
set -euo pipefail
cd "$(dirname "$0")"

swift build -c release --product Pulse
BIN="$(swift build -c release --show-bin-path)/Pulse"
APP="../Pulse.app"

# Replace only Pulse's own previous build.
if [ -d "$APP" ] && grep -q "local.projectpulse.Pulse" "$APP/Contents/Info.plist" 2>/dev/null; then
  rm -rf "$APP"
fi
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/Pulse"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Pulse</string>
  <key>CFBundleDisplayName</key><string>Pulse</string>
  <key>CFBundleIdentifier</key><string>local.projectpulse.Pulse</string>
  <key>CFBundleExecutable</key><string>Pulse</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.developer-tools</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST
codesign --force --sign - "$APP" >/dev/null 2>&1  # local signature so macOS runs it as one app
echo "Built $(cd .. && pwd)/Pulse.app"
