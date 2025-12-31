#!/bin/bash
set -e

APP_NAME="sideload"
APP_ID="io.github.shiro.Sideload"

echo "🗑️ 卸载 Sideload..."

rm -f ~/.local/bin/$APP_NAME
rm -rf ~/.local/share/$APP_NAME
rm -f ~/.local/share/applications/$APP_ID.desktop

update-desktop-database ~/.local/share/applications/ 2>/dev/null || true

echo "✓ 卸载完成"
