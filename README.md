<p align="center">
  <img src="https://img.shields.io/badge/GTK-4.0-4A86CF?style=flat-square&logo=gtk" alt="GTK4">
  <img src="https://img.shields.io/badge/Libadwaita-1.0-4A86CF?style=flat-square" alt="Libadwaita">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/Platform-Linux-FCC624?style=flat-square&logo=linux&logoColor=black" alt="Platform">
</p>

# Sideload

在 Fedora/GNOME 上安装和管理第三方软件包。

## 功能

- 支持 `.deb` 和 `.tar.gz` 格式
- 拖放安装
- Distrobox 容器隔离安装（仅 DEB）
- 应用管理：编辑图标、名称、启动命令
- 自动创建桌面图标和菜单项

## 安装

```bash
# 依赖
sudo dnf install python3-gobject gtk4 libadwaita

# 安装
git clone https://github.com/shiro123444/sideload.git
cd sideload
./install.sh
```

## 使用

- 拖放软件包到窗口
- 或点击选择文件
- 或命令行：`sideload /path/to/package.deb`

## 项目结构

```
sideload/
├── sideload.py      # 主程序
├── install.sh       # 安装脚本
├── uninstall.sh     # 卸载脚本
├── LICENSE          # MIT 许可证
└── README.md
```

## 技术栈

| 组件 | 技术 |
|------|------|
| UI 框架 | GTK4 + Libadwaita |
| 语言 | Python 3 |
| 容器 | Distrobox (可选) |
| 桌面集成 | XDG Desktop Entry |

## 许可证

MIT License © 2024
