#!/bin/bash
set -e

APP_NAME="sideload"
APP_ID="io.github.shiro.Sideload"

echo "📦 安装 Sideload..."

mkdir -p ~/.local/bin
mkdir -p ~/.local/share/applications
mkdir -p ~/.local/share/$APP_NAME

cp sideload.py ~/.local/share/$APP_NAME/
chmod +x ~/.local/share/$APP_NAME/sideload.py

cat > ~/.local/bin/$APP_NAME << EOF
#!/bin/bash
exec python3 ~/.local/share/$APP_NAME/sideload.py "\$@"
EOF
chmod +x ~/.local/bin/$APP_NAME

cat > ~/.local/share/applications/$APP_ID.desktop << EOF
[Desktop Entry]
Name=Sideload
Name[zh_CN]=软件包安装器
Comment=Install third-party packages
Comment[zh_CN]=安装第三方软件包
Exec=$HOME/.local/bin/$APP_NAME %F
Icon=package-x-generic
Type=Application
StartupNotify=true
Categories=System;PackageManager;
MimeType=application/vnd.debian.binary-package;application/x-compressed-tar;application/gzip;
Keywords=deb;package;installer;tar;sideload;
EOF

update-desktop-database ~/.local/share/applications/ 2>/dev/null || true

echo "✓ 安装完成"
echo "  运行: sideload"
