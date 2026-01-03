#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Package Installer - 优雅的软件包安装器
适配 Fedora/GNOME (Wayland/X11)
使用 GTK4 + Libadwaita 构建

支持格式: DEB, tar.gz, tgz
安装模式: 直接安装 / Distrobox 容器隔离

作者: Shiro
许可: MIT License
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, Gio, GLib, Gdk
import subprocess
import os
import tempfile
import shutil
import threading
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Callable
from enum import Enum, auto

# ============================================================================
# 配置常量
# ============================================================================

APP_ID = "io.github.shiro.Sideload"
APP_NAME = "Sideload"
APP_VERSION = "1.0.0"
APP_WEBSITE = "https://github.com/shiro/sideload"

DISTROBOX_CONTAINER = "ubuntu-apps"
DISTROBOX_IMAGE = "ubuntu:24.04"

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# 枚举和数据类
# ============================================================================

class PackageType(Enum):
    """软件包类型"""
    DEB = auto()
    TAR_GZ = auto()
    UNKNOWN = auto()


class InstallMode(Enum):
    """安装模式"""
    DIRECT = auto()      # 直接安装到 ~/.local
    DISTROBOX = auto()   # Distrobox 容器隔离


@dataclass
class InstallResult:
    """安装结果"""
    success: bool
    message: str
    app_name: str = ""
    executable: Optional[Path] = None
    via_distrobox: bool = False


@dataclass
class Package:
    """软件包信息"""
    path: Path
    name: str = ""
    version: str = ""
    description: str = ""
    icon: Optional[Path] = None
    desktop_file: Optional[Path] = None
    extract_dir: Optional[Path] = None
    package_type: PackageType = PackageType.UNKNOWN
    
    def __post_init__(self):
        self.path = Path(self.path)
        self.package_type = self._detect_type()
    
    def _detect_type(self) -> PackageType:
        """检测包类型"""
        name = self.path.name.lower()
        if name.endswith('.deb'):
            return PackageType.DEB
        elif name.endswith('.tar.gz') or name.endswith('.tgz'):
            return PackageType.TAR_GZ
        return PackageType.UNKNOWN
    
    def extract(self) -> bool:
        """解压软件包"""
        self.extract_dir = Path(tempfile.mkdtemp(prefix="pkg-installer-"))
        try:
            if self.package_type == PackageType.DEB:
                return self._extract_deb()
            elif self.package_type == PackageType.TAR_GZ:
                return self._extract_targz()
            return False
        except Exception as e:
            logger.error(f"解压失败: {e}")
            return False
    
    def _extract_deb(self) -> bool:
        """解压 DEB 包"""
        result = subprocess.run(
            ['dpkg-deb', '-x', str(self.path), str(self.extract_dir)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            # 回退到 ar 解压
            subprocess.run(['ar', 'x', str(self.path)], cwd=self.extract_dir, check=True)
            for f in self.extract_dir.iterdir():
                if f.name.startswith('data.tar'):
                    subprocess.run(['tar', '-xf', str(f)], cwd=self.extract_dir, check=True)
                    break
        
        self._parse_deb_info()
        return True
    
    def _extract_targz(self) -> bool:
        """解压 tar.gz 包"""
        subprocess.run(
            ['tar', '-xzf', str(self.path), '-C', str(self.extract_dir)],
            check=True
        )
        self._parse_targz_info()
        return True
    
    def _parse_deb_info(self):
        """解析 DEB 包信息"""
        # 从文件名提取
        parts = self.path.stem.split('_')
        self.name = parts[0] if parts else self.path.stem
        self.version = parts[1] if len(parts) > 1 else ""
        
        # 从 .desktop 文件获取更多信息
        for desktop in self.extract_dir.rglob('*.desktop'):
            if 'url-handler' not in desktop.name.lower():
                self.desktop_file = desktop
                self._parse_desktop_file(desktop)
                break
        
        self._find_icon()
    
    def _parse_targz_info(self):
        """解析 tar.gz 包信息"""
        name = self.path.name.replace('.tar.gz', '').replace('.tgz', '')
        parts = name.split('-')
        
        # 查找可执行文件确定名称
        executables = [f for f in self.extract_dir.rglob('*') 
                      if f.is_file() and os.access(f, os.X_OK)]
        
        if len(executables) == 1:
            self.name = executables[0].stem
        else:
            self.name = parts[0] if parts else name
        
        # 提取版本号
        for part in parts:
            if part and part[0].isdigit():
                self.version = part
                break
        
        self.description = f"{self.name} 应用程序"
        self._find_icon_deep()
    
    def _parse_desktop_file(self, path: Path):
        """解析 .desktop 文件"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('Name='):
                        self.name = line.split('=', 1)[1].strip()
                    elif line.startswith('Comment='):
                        self.description = line.split('=', 1)[1].strip()
        except Exception as e:
            logger.warning(f"解析 desktop 文件失败: {e}")
    
    def _find_icon(self):
        """查找图标（DEB 包）"""
        search_dirs = [
            self.extract_dir / 'usr' / 'share' / 'pixmaps',
            self.extract_dir / 'usr' / 'share' / 'icons',
        ]
        
        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            
            # 优先查找大尺寸 PNG
            for pattern in ['**/256*/*.png', '**/128*/*.png', '**/*.png', '**/*.svg']:
                icons = list(search_dir.glob(pattern))
                if icons:
                    self.icon = icons[0]
                    return
    
    def _find_icon_deep(self):
        """深度查找图标（tar.gz 包）"""
        all_icons = []
        for ext in ['png', 'svg', 'ico', 'xpm']:
            all_icons.extend(self.extract_dir.rglob(f'*.{ext}'))
        
        if not all_icons:
            return
        
        def score(icon: Path) -> int:
            s = 0
            name = icon.name.lower()
            path_str = str(icon).lower()
            
            if 'icon' in name or 'logo' in name:
                s += 100
            if self.name.lower() in name:
                s += 50
            for size in ['256', '128', '64', '48']:
                if size in path_str:
                    s += int(size)
                    break
            if icon.suffix == '.png':
                s += 10
            return s
        
        all_icons.sort(key=score, reverse=True)
        self.icon = all_icons[0]
        logger.info(f"选择图标: {self.icon.name}")
    
    def cleanup(self):
        """清理临时文件"""
        if self.extract_dir and self.extract_dir.exists():
            shutil.rmtree(self.extract_dir, ignore_errors=True)


# ============================================================================
# 安装器核心逻辑
# ============================================================================

class PackageInstaller:
    """软件包安装器"""
    
    def __init__(self):
        self.install_base = Path.home() / '.local' / 'share'
        self.bin_dir = Path.home() / '.local' / 'bin'
        self.icons_dir = Path.home() / '.local' / 'share' / 'icons'
        self.apps_dir = Path.home() / '.local' / 'share' / 'applications'
        self.desktop_dir = self._get_desktop_dir()
        
        # 确保目录存在
        for d in [self.bin_dir, self.icons_dir, self.apps_dir]:
            d.mkdir(parents=True, exist_ok=True)
    
    def _get_desktop_dir(self) -> Path:
        """获取桌面目录"""
        for name in ['桌面', 'Desktop']:
            path = Path.home() / name
            if path.exists():
                return path
        return Path.home() / 'Desktop'
    
    def _get_terminal_command(self) -> Tuple[Optional[str], List[str]]:
        """获取系统默认终端"""
        terminals = [
            ('xdg-terminal-exec', []),
            ('ptyxis', ['--']),
            ('kgx', ['--']),
            ('gnome-terminal', ['--']),
            ('konsole', ['-e']),
            ('xfce4-terminal', ['-e']),
            ('xterm', ['-e']),
        ]
        
        for term, args in terminals:
            if shutil.which(term):
                return term, args
        return None, []
    
    def install(self, pkg: Package, mode: InstallMode, 
                create_desktop: bool = True, 
                add_to_menu: bool = True) -> InstallResult:
        """安装软件包"""
        try:
            if mode == InstallMode.DISTROBOX and pkg.package_type == PackageType.DEB:
                return self._install_distrobox(pkg)
            elif pkg.package_type == PackageType.TAR_GZ:
                return self._install_targz(pkg, create_desktop, add_to_menu)
            else:
                return self._install_deb(pkg, create_desktop, add_to_menu)
        except Exception as e:
            logger.exception("安装失败")
            return InstallResult(False, f"安装失败: {e}")
    
    def _install_deb(self, pkg: Package, create_desktop: bool, add_to_menu: bool) -> InstallResult:
        """安装 DEB 包"""
        app_name = pkg.name
        app_name_lower = app_name.lower().replace(' ', '-')
        
        # 1. 寻找主程序目录 (优先级: opt > usr/lib > usr/share)
        source_dir = None
        install_mode = "dir" # dir or bin
        
        # 检查 /opt
        opt_dir = pkg.extract_dir / 'opt'
        if opt_dir.exists():
            for d in opt_dir.iterdir():
                if d.is_dir():
                    source_dir = d
                    break
        
        # 检查 usr/lib 和 usr/share
        if not source_dir:
            search_dirs = [
                pkg.extract_dir / 'usr' / 'lib',
                pkg.extract_dir / 'usr' / 'share'
            ]
            search_names = [app_name_lower, app_name, pkg.path.stem.split('_')[0]]
            
            for base_dir in search_dirs:
                if not base_dir.exists(): continue
                for name in search_names:
                    candidate = base_dir / name
                    if candidate.exists() and candidate.is_dir():
                        source_dir = candidate
                        break
                if source_dir: break
        
        # 检查 usr/bin (如果没找到目录，可能是散装的)
        if not source_dir:
            bin_dir = pkg.extract_dir / 'usr' / 'bin'
            if bin_dir.exists() and any(bin_dir.iterdir()):
                source_dir = bin_dir
                install_mode = "bin"

        executable_path = None
        final_install_dir = self.install_base / app_name_lower

        # 2. 执行安装
        if source_dir:
            if final_install_dir.exists():
                shutil.rmtree(final_install_dir)
            
            if install_mode == "dir":
                # 复制整个目录
                shutil.copytree(source_dir, final_install_dir)
                
                # 在安装目录中查找可执行文件
                # 优先级: 同名文件 > 任何可执行文件
                candidates = []
                for root, dirs, files in os.walk(final_install_dir):
                    for file in files:
                        path = Path(root) / file
                        if os.access(path, os.X_OK) and not path.suffix in ['.so', '.a', '.sh', '.png', '.svg', '.jpg', '.txt', '.md']:
                            candidates.append(path)
                
                # 筛选最佳候选
                for c in candidates:
                    if c.stem.lower() in [app_name_lower, app_name.lower(), 'kiro-account-manager']:
                        executable_path = c
                        break
                
                if not executable_path and candidates:
                    executable_path = candidates[0] # 默认取第一个
                    
            elif install_mode == "bin":
                # 复制 bin 目录内容
                final_install_dir.mkdir(parents=True, exist_ok=True)
                for f in source_dir.iterdir():
                    if f.is_file():
                        shutil.copy2(f, final_install_dir)
                        if f.stem.lower() == app_name_lower:
                            executable_path = final_install_dir / f.name
                
                if not executable_path:
                     # 找一个看起来像主程序的
                    for f in final_install_dir.iterdir():
                        if os.access(f, os.X_OK):
                            executable_path = f
                            break

        # 3. 处理依赖库 (usr/lib)
        # 如果有 usr/lib，将其复制到安装目录下的 lib 文件夹，以便设置 LD_LIBRARY_PATH
        pkg_lib_dir = pkg.extract_dir / 'usr' / 'lib'
        if pkg_lib_dir.exists() and final_install_dir.exists():
            target_lib_dir = final_install_dir / 'lib'
            # 如果是 bin 模式，或者 dir 模式下没有 lib 目录，则复制
            if not target_lib_dir.exists():
                try:
                    shutil.copytree(pkg_lib_dir, target_lib_dir, dirs_exist_ok=True)
                except Exception as e:
                    logger.warning(f"复制库文件失败: {e}")

        # 4. 创建启动脚本 (Wrapper)
        if executable_path:
            wrapper_path = self.bin_dir / app_name_lower
            
            # 构建 LD_LIBRARY_PATH
            lib_paths = []
            if (final_install_dir / 'lib').exists():
                lib_paths.append(str(final_install_dir / 'lib'))
            if (final_install_dir / 'usr' / 'lib').exists(): # 有些结构保留了 usr/lib
                lib_paths.append(str(final_install_dir / 'usr' / 'lib'))
            
            ld_path_str = f"export LD_LIBRARY_PATH=\"{':'.join(lib_paths)}:$LD_LIBRARY_PATH\"" if lib_paths else ""
            
            with open(wrapper_path, 'w') as f:
                f.write('#!/bin/bash\n')
                if ld_path_str:
                    f.write(f'{ld_path_str}\n')
                f.write(f'exec "{executable_path}" "$@"\n')
            
            wrapper_path.chmod(0o755)

        # 安装图标
        self._install_icon(pkg)
        
        # 处理 desktop 文件
        if pkg.desktop_file and add_to_menu:
            self._process_desktop_file(pkg.desktop_file, app_name_lower, 
                                       executable_path, create_desktop)
        
        return InstallResult(
            success=True,
            message=f"{app_name} 已成功安装",
            app_name=app_name_lower,
            executable=executable_path
        )
    
    def _install_targz(self, pkg: Package, create_desktop: bool, add_to_menu: bool) -> InstallResult:
        """安装 tar.gz 包"""
        app_name = pkg.name
        app_name_lower = app_name.lower().replace(' ', '-')
        
        logger.info(f"开始安装 tar.gz 包: {app_name}")
        
        # 查找可执行文件
        executables = [f for f in pkg.extract_dir.rglob('*')
                      if f.is_file() and os.access(f, os.X_OK) 
                      and not f.suffix in ['.so', '.a', '.sh']]
        
        if not executables:
            return InstallResult(False, "未找到可执行文件")
        
        # 安装到用户目录
        install_dir = self.install_base / app_name_lower
        if install_dir.exists():
            shutil.rmtree(install_dir)
        shutil.copytree(pkg.extract_dir, install_dir)
        
        # 创建符号链接
        main_exec = executables[0]
        rel_path = main_exec.relative_to(pkg.extract_dir)
        actual_exec = install_dir / rel_path
        
        link_path = self.bin_dir / app_name_lower
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()
        link_path.symlink_to(actual_exec)
        
        # 安装图标
        icon_path = self._install_icon(pkg, app_name_lower)
        
        # 检测是否为服务器程序
        is_server = self._detect_server_app(actual_exec)
        
        # 创建 desktop 文件
        if add_to_menu:
            self._create_desktop_file(
                app_name, app_name_lower, actual_exec,
                icon_path, is_server, create_desktop
            )
        
        logger.info(f"{app_name} 安装完成")
        
        return InstallResult(
            success=True,
            message=f"{app_name} 已成功安装",
            app_name=app_name_lower,
            executable=actual_exec
        )
    
    def _install_distrobox(self, pkg: Package) -> InstallResult:
        """使用 Distrobox 安装"""
        app_name = pkg.name
        
        if not shutil.which('distrobox'):
            return InstallResult(False, "请先安装 distrobox: sudo dnf install distrobox")
        
        # 检查/创建容器
        result = subprocess.run(['distrobox', 'list', '--no-color'], 
                               capture_output=True, text=True)
        
        if DISTROBOX_CONTAINER not in result.stdout:
            logger.info(f"创建容器 {DISTROBOX_CONTAINER}...")
            create_result = subprocess.run(
                ['distrobox', 'create', '-i', DISTROBOX_IMAGE, '-n', DISTROBOX_CONTAINER, '-Y'],
                capture_output=True, text=True
            )
            if create_result.returncode != 0:
                return InstallResult(False, f"创建容器失败: {create_result.stderr}")
        
        # 在容器中安装
        subprocess.run([
            'distrobox', 'enter', '-n', DISTROBOX_CONTAINER, '--',
            'sudo', 'apt', 'install', '-y', str(pkg.path)
        ], capture_output=True, text=True)
        
        # 修复依赖
        subprocess.run([
            'distrobox', 'enter', '-n', DISTROBOX_CONTAINER, '--',
            'sudo', 'apt', 'install', '-f', '-y'
        ], capture_output=True, text=True)
        
        # 导出应用
        app_name_lower = app_name.lower().replace(' ', '-')
        subprocess.run([
            'distrobox', 'enter', '-n', DISTROBOX_CONTAINER, '--',
            'distrobox-export', '--app', app_name_lower
        ], capture_output=True, text=True)
        
        return InstallResult(
            success=True,
            message=f"{app_name} 已通过 Distrobox 安装到 {DISTROBOX_CONTAINER} 容器",
            app_name=app_name_lower,
            via_distrobox=True
        )
    
    def _install_icon(self, pkg: Package, name_hint: str = None) -> Optional[str]:
        """安装图标"""
        if not pkg.icon or not pkg.icon.exists():
            return None
        
        try:
            if name_hint:
                dest = self.icons_dir / f"{name_hint}{pkg.icon.suffix}"
            else:
                dest = self.icons_dir / pkg.icon.name
            shutil.copy2(pkg.icon, dest)
            return str(dest)
        except Exception as e:
            logger.warning(f"图标安装失败: {e}")
            return None
    
    def _detect_server_app(self, executable: Path) -> bool:
        """检测是否为服务器程序"""
        try:
            result = subprocess.run(
                [str(executable), '--help'],
                capture_output=True, text=True, timeout=2
            )
            help_text = (result.stdout + result.stderr).lower()
            return any(word in help_text for word in ['server', 'serve', 'daemon', 'start', 'stop'])
        except:
            return False
    
    def _create_desktop_file(self, app_name: str, app_name_lower: str,
                            executable: Path, icon_path: Optional[str],
                            is_server: bool, create_desktop_icon: bool):
        """创建 .desktop 文件"""
        icon_line = icon_path if icon_path else "application-x-executable"
        
        if is_server:
            # 创建启动脚本
            launcher = self.bin_dir / f"{app_name_lower}-launcher.sh"
            launcher.write_text(f'''#!/bin/bash
# {app_name} 启动器
echo "正在启动 {app_name} 服务器..."
echo "================================"
{executable} server
echo ""
echo "================================"
echo "服务器已停止，按任意键关闭..."
read -n 1
''')
            launcher.chmod(0o755)
            
            term_cmd, term_args = self._get_terminal_command()
            if term_cmd:
                args_str = ' '.join(term_args) + ' ' if term_args else ''
                exec_line = f"{term_cmd} {args_str}{launcher}"
                terminal = "false"
            else:
                exec_line = str(launcher)
                terminal = "true"
        else:
            exec_line = str(executable)
            terminal = "false"
        
        desktop_content = f"""[Desktop Entry]
Name={app_name}
Comment={app_name} Application
GenericName={app_name}
Exec={exec_line}
Icon={icon_line}
Type=Application
StartupNotify=false
StartupWMClass={app_name}
Categories=Utility;
Keywords={app_name_lower};
Terminal={terminal}
"""
        
        # 写入应用目录
        desktop_file = self.apps_dir / f"{app_name_lower}.desktop"
        desktop_file.write_text(desktop_content)
        logger.info(f"创建菜单项: {desktop_file}")
        
        # 写入桌面
        if create_desktop_icon and self.desktop_dir.exists():
            desktop_path = self.desktop_dir / f"{app_name_lower}.desktop"
            desktop_path.write_text(desktop_content)
            desktop_path.chmod(0o755)
            
            # 设置可信任
            subprocess.run(
                ['gio', 'set', str(desktop_path), 'metadata::trusted', 'true'],
                capture_output=True
            )
        
        # 更新数据库
        subprocess.run(['update-desktop-database', str(self.apps_dir)], capture_output=True)
    
    def _process_desktop_file(self, src: Path, app_name_lower: str,
                             executable: Optional[Path], create_desktop: bool):
        """处理现有的 .desktop 文件"""
        lines = []
        with open(src, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('Exec='):
                    if executable:
                        exec_cmd = line.split('=', 1)[1].strip()
                        args = exec_cmd.split()[1:] if ' ' in exec_cmd else []
                        lines.append(f"Exec={executable} {' '.join(args)}\n".strip() + '\n')
                    else:
                        new_line = line.replace('/usr/share/', str(self.install_base) + '/')
                        new_line = new_line.replace('/opt/', str(self.install_base) + '/')
                        lines.append(new_line)
                elif line.startswith('Icon='):
                    icon_name = line.split('=', 1)[1].strip()
                    icon_path = self.icons_dir / f"{icon_name}.png"
                    if icon_path.exists():
                        lines.append(f"Icon={icon_path}\n")
                    elif (self.icons_dir / icon_name).exists():
                        lines.append(f"Icon={self.icons_dir / icon_name}\n")
                    else:
                        lines.append(line)
                else:
                    lines.append(line)
        
        # 写入应用目录
        apps_desktop = self.apps_dir / src.name
        apps_desktop.write_text(''.join(lines))
        
        # 写入桌面
        if create_desktop and self.desktop_dir.exists():
            desktop_file = self.desktop_dir / src.name
            desktop_file.write_text(''.join(lines))
            desktop_file.chmod(0o755)
            subprocess.run(
                ['gio', 'set', str(desktop_file), 'metadata::trusted', 'true'],
                capture_output=True
            )
        
        subprocess.run(['update-desktop-database', str(self.apps_dir)], capture_output=True)
    
    def uninstall(self, app_name: str) -> bool:
        """卸载应用"""
        app_name_lower = app_name.lower().replace(' ', '-')
        
        # 删除程序目录
        app_dir = self.install_base / app_name_lower
        if app_dir.exists():
            shutil.rmtree(app_dir, ignore_errors=True)
        
        # 删除符号链接
        link = self.bin_dir / app_name_lower
        if link.exists() or link.is_symlink():
            link.unlink()
        
        # 删除 desktop 文件
        for d in [self.apps_dir, self.desktop_dir]:
            for f in d.glob(f'*{app_name_lower}*'):
                f.unlink()
        
        # 删除启动脚本
        launcher = self.bin_dir / f"{app_name_lower}-launcher.sh"
        if launcher.exists():
            launcher.unlink()
        
        return True
    
    def get_installed_apps(self) -> List[Tuple[str, str]]:
        """获取已安装的应用列表"""
        apps = []
        for desktop in self.apps_dir.glob('*.desktop'):
            try:
                content = desktop.read_text()
                if '.local/share' in content:
                    name = desktop.stem
                    for line in content.split('\n'):
                        if line.startswith('Name='):
                            name = line.split('=', 1)[1]
                            break
                    apps.append((name, desktop.name))
            except:
                pass
        return apps


# ============================================================================
# CSS 样式
# ============================================================================

CSS_STYLES = """
/* 主窗口毛玻璃效果 */
window.background {
    background: alpha(@window_bg_color, 0.95);
}

/* 拖放区域 */
.drop-zone {
    border: 2px dashed alpha(@accent_color, 0.4);
    border-radius: 24px;
    background: alpha(@accent_color, 0.03);
    transition: all 250ms cubic-bezier(0.4, 0, 0.2, 1);
}

.drop-zone:hover {
    border-color: alpha(@accent_color, 0.6);
    background: alpha(@accent_color, 0.06);
}

.drop-zone-active {
    border-color: @accent_color;
    border-style: solid;
    background: alpha(@accent_color, 0.1);
    box-shadow: 0 0 0 4px alpha(@accent_color, 0.15);
}

/* 应用图标 */
.app-icon {
    border-radius: 18px;
    box-shadow: 0 4px 12px alpha(black, 0.15);
    transition: transform 200ms ease;
}

.app-icon:hover {
    transform: scale(1.05);
}

/* 卡片样式 */
.package-card {
    border-radius: 16px;
    background: alpha(@card_bg_color, 0.6);
    box-shadow: 0 1px 3px alpha(black, 0.08);
    transition: all 200ms ease;
}

.package-card:hover {
    background: alpha(@card_bg_color, 0.8);
    box-shadow: 0 4px 12px alpha(black, 0.12);
}

/* 安装按钮 */
.install-button {
    padding: 14px 42px;
    border-radius: 14px;
    font-weight: 600;
    font-size: 15px;
    transition: all 150ms ease;
}

.install-button:hover {
    box-shadow: 0 4px 12px alpha(@accent_color, 0.3);
}

/* 状态颜色 */
.success { color: #2ec27e; }
.error { color: #e01b24; }
.warning { color: #e5a50a; }

/* 功能图标 */
.feature-icon {
    background: alpha(@accent_color, 0.08);
    border-radius: 12px;
    padding: 12px;
    transition: all 200ms ease;
}

.feature-icon:hover {
    background: alpha(@accent_color, 0.15);
    transform: translateY(-2px);
}

/* 完成页面动画 */
.success-icon {
    animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.7; }
}

/* 加载动画 */
.loading-spinner {
    animation: spin 1s linear infinite;
}

@keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
}

/* 提示框 */
.tip-box {
    background: alpha(@accent_color, 0.05);
    border-radius: 12px;
    padding: 16px;
    border-left: 3px solid @accent_color;
}

/* 列表项悬停 */
row:hover {
    background: alpha(@accent_color, 0.05);
}
"""


# ============================================================================
# UI 组件
# ============================================================================

class InstallerWindow(Adw.ApplicationWindow):
    """主窗口"""
    
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title(APP_NAME)
        self.set_default_size(580, 680)
        
        self.package: Optional[Package] = None
        self.installer = PackageInstaller()
        self.install_result: Optional[InstallResult] = None
        
        self._setup_css()
        self._setup_ui()
        self._setup_drag_drop()
    
    def _setup_css(self):
        """加载 CSS 样式"""
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS_STYLES.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    
    def _setup_ui(self):
        """构建 UI"""
        # 主容器
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)
        
        # 头部栏
        header = Adw.HeaderBar()
        header.add_css_class("flat")
        
        # 菜单按钮
        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")
        menu_btn.set_tooltip_text("菜单")
        
        menu = Gio.Menu()
        menu.append("已安装的应用", "app.installed")
        menu.append("关于", "app.about")
        menu_btn.set_menu_model(menu)
        header.pack_end(menu_btn)
        
        toolbar_view.add_top_bar(header)
        
        # Toast 覆盖层
        self.toast_overlay = Adw.ToastOverlay()
        toolbar_view.set_content(self.toast_overlay)
        
        # 滚动容器
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.toast_overlay.set_child(scroll)
        
        # 主内容
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main_box.set_margin_start(24)
        main_box.set_margin_end(24)
        main_box.set_margin_top(8)
        main_box.set_margin_bottom(24)
        scroll.set_child(main_box)
        
        # 视图栈
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(250)
        main_box.append(self.stack)
        
        # 添加视图
        self.stack.add_named(self._create_drop_view(), "drop")
        self.stack.add_named(self._create_package_view(), "package")
        self.stack.add_named(self._create_complete_view(), "complete")
    
    def _create_drop_view(self) -> Gtk.Widget:
        """创建拖放视图"""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=28)
        box.set_valign(Gtk.Align.CENTER)
        box.set_vexpand(True)
        
        # 标题区域
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        title_box.set_halign(Gtk.Align.CENTER)
        
        # 应用图标
        app_icon = Gtk.Image.new_from_icon_name("package-x-generic-symbolic")
        app_icon.set_pixel_size(48)
        app_icon.add_css_class("dim-label")
        title_box.append(app_icon)
        
        title = Gtk.Label(label=APP_NAME)
        title.add_css_class("title-1")
        title_box.append(title)
        
        subtitle = Gtk.Label(label="支持 DEB 和 tar.gz 格式")
        subtitle.add_css_class("dim-label")
        title_box.append(subtitle)
        
        box.append(title_box)
        
        # 拖放区域
        self.drop_zone = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.drop_zone.set_halign(Gtk.Align.CENTER)
        self.drop_zone.set_valign(Gtk.Align.CENTER)
        self.drop_zone.set_size_request(380, 220)
        self.drop_zone.add_css_class("drop-zone")
        
        drop_icon = Gtk.Image.new_from_icon_name("document-open-symbolic")
        drop_icon.set_pixel_size(48)
        drop_icon.add_css_class("dim-label")
        self.drop_zone.append(drop_icon)
        
        drop_label = Gtk.Label(label="拖放软件包到这里")
        drop_label.add_css_class("title-4")
        self.drop_zone.append(drop_label)
        
        drop_hint = Gtk.Label(label="或点击下方按钮选择")
        drop_hint.add_css_class("dim-label")
        drop_hint.add_css_class("caption")
        self.drop_zone.append(drop_hint)
        
        box.append(self.drop_zone)
        
        # 选择按钮
        select_btn = Gtk.Button(label="选择软件包")
        select_btn.add_css_class("pill")
        select_btn.add_css_class("suggested-action")
        select_btn.set_halign(Gtk.Align.CENTER)
        select_btn.connect("clicked", self._on_select_file)
        box.append(select_btn)
        
        # 功能展示
        features_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=32)
        features_box.set_halign(Gtk.Align.CENTER)
        features_box.set_margin_top(24)
        
        features = [
            ("archive-extract-symbolic", "自动解压"),
            ("emblem-system-symbolic", "智能安装"),
            ("computer-symbolic", "桌面集成"),
        ]
        
        for icon_name, label_text in features:
            feature = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            feature.set_halign(Gtk.Align.CENTER)
            
            icon_box = Gtk.Box()
            icon_box.set_halign(Gtk.Align.CENTER)
            icon_box.add_css_class("feature-icon")
            icon = Gtk.Image.new_from_icon_name(icon_name)
            icon.set_pixel_size(20)
            icon_box.append(icon)
            feature.append(icon_box)
            
            label = Gtk.Label(label=label_text)
            label.add_css_class("caption")
            label.add_css_class("dim-label")
            feature.append(label)
            
            features_box.append(feature)
        
        box.append(features_box)
        
        return box
    
    def _create_package_view(self) -> Gtk.Widget:
        """创建包信息视图"""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_valign(Gtk.Align.CENTER)
        box.set_vexpand(True)
        
        # 包信息卡片
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        card.add_css_class("package-card")
        card.set_margin_start(16)
        card.set_margin_end(16)
        card.set_margin_top(16)
        card.set_margin_bottom(16)
        
        # 图标和信息
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        header.set_halign(Gtk.Align.CENTER)
        
        self.pkg_icon = Gtk.Image.new_from_icon_name("package-x-generic")
        self.pkg_icon.set_pixel_size(80)
        self.pkg_icon.add_css_class("app-icon")
        header.append(self.pkg_icon)
        
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        info.set_valign(Gtk.Align.CENTER)
        
        self.pkg_name = Gtk.Label(label="应用名称")
        self.pkg_name.add_css_class("title-2")
        self.pkg_name.set_halign(Gtk.Align.START)
        info.append(self.pkg_name)
        
        self.pkg_version = Gtk.Label(label="")
        self.pkg_version.add_css_class("dim-label")
        self.pkg_version.add_css_class("caption")
        self.pkg_version.set_halign(Gtk.Align.START)
        info.append(self.pkg_version)
        
        self.pkg_desc = Gtk.Label(label="")
        self.pkg_desc.set_wrap(True)
        self.pkg_desc.set_max_width_chars(35)
        self.pkg_desc.set_halign(Gtk.Align.START)
        self.pkg_desc.add_css_class("dim-label")
        info.append(self.pkg_desc)
        
        header.append(info)
        card.append(header)
        
        # 分隔线
        card.append(Gtk.Separator())
        
        # 选项列表
        options = Gtk.ListBox()
        options.set_selection_mode(Gtk.SelectionMode.NONE)
        options.add_css_class("boxed-list")
        
        self.desktop_switch = Adw.SwitchRow()
        self.desktop_switch.set_title("创建桌面图标")
        self.desktop_switch.set_active(True)
        options.append(self.desktop_switch)
        
        self.menu_switch = Adw.SwitchRow()
        self.menu_switch.set_title("添加到应用菜单")
        self.menu_switch.set_active(True)
        options.append(self.menu_switch)
        
        card.append(options)
        
        # 安装模式
        mode_label = Gtk.Label(label="安装模式")
        mode_label.add_css_class("heading")
        mode_label.set_halign(Gtk.Align.START)
        mode_label.set_margin_top(8)
        card.append(mode_label)
        
        mode_list = Gtk.ListBox()
        mode_list.set_selection_mode(Gtk.SelectionMode.NONE)
        mode_list.add_css_class("boxed-list")
        
        self.direct_mode = Adw.ActionRow()
        self.direct_mode.set_title("直接安装")
        self.direct_mode.set_subtitle("安装到 ~/.local")
        self.direct_radio = Gtk.CheckButton()
        self.direct_radio.set_active(True)
        self.direct_mode.add_prefix(self.direct_radio)
        self.direct_mode.set_activatable_widget(self.direct_radio)
        mode_list.append(self.direct_mode)
        
        self.distrobox_mode = Adw.ActionRow()
        self.distrobox_mode.set_title("容器隔离安装")
        self.distrobox_mode.set_subtitle("使用 Distrobox 隔离环境")
        self.distrobox_radio = Gtk.CheckButton()
        self.distrobox_radio.set_group(self.direct_radio)
        self.distrobox_mode.add_prefix(self.distrobox_radio)
        self.distrobox_mode.set_activatable_widget(self.distrobox_radio)
        mode_list.append(self.distrobox_mode)
        
        card.append(mode_list)
        
        # 卡片容器
        card_frame = Gtk.Frame()
        card_frame.set_child(card)
        card_frame.add_css_class("card")
        box.append(card_frame)
        
        # 按钮
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_box.set_halign(Gtk.Align.CENTER)
        
        back_btn = Gtk.Button(label="返回")
        back_btn.add_css_class("pill")
        back_btn.connect("clicked", self._on_back)
        btn_box.append(back_btn)
        
        self.install_btn = Gtk.Button(label="安装")
        self.install_btn.add_css_class("pill")
        self.install_btn.add_css_class("suggested-action")
        self.install_btn.add_css_class("install-button")
        self.install_btn.connect("clicked", self._on_install)
        btn_box.append(self.install_btn)
        
        box.append(btn_box)
        
        return box
    
    def _create_complete_view(self) -> Gtk.Widget:
        """创建完成视图"""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_valign(Gtk.Align.CENTER)
        box.set_vexpand(True)
        
        self.complete_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        self.complete_icon.set_pixel_size(72)
        self.complete_icon.add_css_class("success")
        self.complete_icon.add_css_class("success-icon")
        box.append(self.complete_icon)
        
        self.complete_title = Gtk.Label(label="安装成功")
        self.complete_title.add_css_class("title-1")
        box.append(self.complete_title)
        
        self.complete_desc = Gtk.Label(label="")
        self.complete_desc.add_css_class("dim-label")
        self.complete_desc.set_wrap(True)
        box.append(self.complete_desc)
        
        # 提示框
        self.tips_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.tips_box.add_css_class("tip-box")
        self.tips_box.set_margin_top(12)
        self.tips_box.set_margin_start(32)
        self.tips_box.set_margin_end(32)
        box.append(self.tips_box)
        
        # 按钮
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_box.set_halign(Gtk.Align.CENTER)
        btn_box.set_margin_top(20)
        
        self.launch_btn = Gtk.Button(label="启动应用")
        self.launch_btn.add_css_class("pill")
        self.launch_btn.add_css_class("suggested-action")
        self.launch_btn.connect("clicked", self._on_launch)
        btn_box.append(self.launch_btn)
        
        continue_btn = Gtk.Button(label="继续安装")
        continue_btn.add_css_class("pill")
        continue_btn.connect("clicked", self._on_continue)
        btn_box.append(continue_btn)
        
        box.append(btn_box)
        
        return box
    
    def _setup_drag_drop(self):
        """设置拖放"""
        drop_target = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        drop_target.connect("accept", lambda *_: True)
        drop_target.connect("drop", self._on_drop)
        drop_target.connect("enter", self._on_drop_enter)
        drop_target.connect("leave", self._on_drop_leave)
        self.add_controller(drop_target)
    
    def _on_drop_enter(self, target, x, y):
        self.drop_zone.add_css_class("drop-zone-active")
        return Gdk.DragAction.COPY
    
    def _on_drop_leave(self, target):
        self.drop_zone.remove_css_class("drop-zone-active")
    
    def _on_drop(self, target, value, x, y):
        self.drop_zone.remove_css_class("drop-zone-active")
        if isinstance(value, Gio.File):
            path = value.get_path()
            if path and any(path.endswith(ext) for ext in ['.deb', '.tar.gz', '.tgz']):
                self._load_package(path)
                return True
        return False
    
    def _on_select_file(self, btn):
        """选择文件"""
        dialog = Gtk.FileDialog()
        dialog.set_title("选择软件包")
        
        filters = Gio.ListStore.new(Gtk.FileFilter)
        
        all_filter = Gtk.FileFilter()
        all_filter.set_name("所有支持的格式")
        all_filter.add_pattern("*.deb")
        all_filter.add_pattern("*.tar.gz")
        all_filter.add_pattern("*.tgz")
        filters.append(all_filter)
        
        deb_filter = Gtk.FileFilter()
        deb_filter.set_name("DEB 包 (*.deb)")
        deb_filter.add_pattern("*.deb")
        filters.append(deb_filter)
        
        tar_filter = Gtk.FileFilter()
        tar_filter.set_name("tar.gz 包")
        tar_filter.add_pattern("*.tar.gz")
        tar_filter.add_pattern("*.tgz")
        filters.append(tar_filter)
        
        dialog.set_filters(filters)
        dialog.set_default_filter(all_filter)
        
        # 默认打开下载目录
        for name in ['下载', 'Downloads']:
            downloads = Path.home() / name
            if downloads.exists():
                dialog.set_initial_folder(Gio.File.new_for_path(str(downloads)))
                break
        
        dialog.open(self, None, self._on_file_selected)
    
    def _on_file_selected(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                self._load_package(file.get_path())
        except GLib.Error:
            pass
    
    def _load_package(self, path: str):
        """加载软件包"""
        self.package = Package(path)
        self.pkg_name.set_label("正在解析...")
        self.pkg_icon.set_from_icon_name("package-x-generic")
        self.stack.set_visible_child_name("package")
        
        def extract():
            success = self.package.extract()
            GLib.idle_add(self._on_package_loaded, success)
        
        threading.Thread(target=extract, daemon=True).start()
    
    def _on_package_loaded(self, success: bool):
        if success:
            self.pkg_name.set_label(self.package.name)
            self.pkg_version.set_label(f"版本 {self.package.version}" if self.package.version else "")
            self.pkg_desc.set_label(self.package.description or "")
            
            if self.package.icon and self.package.icon.exists():
                try:
                    self.pkg_icon.set_from_file(str(self.package.icon))
                except:
                    pass
            
            # tar.gz 不支持 distrobox
            self.distrobox_mode.set_sensitive(self.package.package_type == PackageType.DEB)
        else:
            self._show_toast("无法解析软件包", True)
            self.stack.set_visible_child_name("drop")
    
    def _on_back(self, btn):
        if self.package:
            self.package.cleanup()
            self.package = None
        self.stack.set_visible_child_name("drop")
    
    def _on_install(self, btn):
        if not self.package:
            return
        
        mode = InstallMode.DISTROBOX if self.distrobox_radio.get_active() else InstallMode.DIRECT
        
        if self.package.package_type == PackageType.TAR_GZ and mode == InstallMode.DISTROBOX:
            self._show_toast("tar.gz 包不支持容器安装")
            mode = InstallMode.DIRECT
        
        self.install_btn.set_sensitive(False)
        self.install_btn.set_label("安装中...")
        
        def install():
            result = self.installer.install(
                self.package, mode,
                self.desktop_switch.get_active(),
                self.menu_switch.get_active()
            )
            GLib.idle_add(self._on_install_complete, result)
        
        threading.Thread(target=install, daemon=True).start()
    
    def _on_install_complete(self, result: InstallResult):
        self.install_btn.set_sensitive(True)
        self.install_btn.set_label("安装")
        self.install_result = result
        
        if result.success:
            self.complete_title.set_label("安装成功")
            self.complete_desc.set_label(result.message)
            self.complete_icon.set_from_icon_name("emblem-ok-symbolic")
            self.complete_icon.remove_css_class("error")
            self.complete_icon.add_css_class("success")
            
            # 更新提示
            while child := self.tips_box.get_first_child():
                self.tips_box.remove(child)
            
            if result.via_distrobox:
                tips = ["在应用菜单中搜索应用", f"容器: {DISTROBOX_CONTAINER}"]
                self.launch_btn.set_sensitive(False)
            else:
                tips = ["在应用菜单中搜索应用", "或双击桌面图标启动"]
                self.launch_btn.set_sensitive(True)
            
            for tip in tips:
                label = Gtk.Label(label=f"• {tip}")
                label.set_halign(Gtk.Align.START)
                label.add_css_class("caption")
                self.tips_box.append(label)
            
            self.stack.set_visible_child_name("complete")
            
            if self.package:
                self.package.cleanup()
        else:
            self._show_toast(result.message, True)
    
    def _on_launch(self, btn):
        if self.install_result and self.install_result.executable:
            try:
                subprocess.Popen([str(self.install_result.executable)], start_new_session=True)
            except Exception as e:
                self._show_toast(f"启动失败: {e}", True)
    
    def _on_continue(self, btn):
        self.package = None
        self.install_result = None
        self.stack.set_visible_child_name("drop")
    
    def _show_toast(self, message: str, is_error: bool = False):
        toast = Adw.Toast(title=message)
        toast.set_timeout(3 if not is_error else 5)
        self.toast_overlay.add_toast(toast)


# ============================================================================
# 应用信息数据类
# ============================================================================

@dataclass
class InstalledApp:
    """已安装应用信息"""
    name: str
    filename: str
    desktop_path: Path
    icon: str = ""
    exec_cmd: str = ""
    comment: str = ""
    categories: str = ""
    terminal: bool = False
    
    @classmethod
    def from_desktop_file(cls, path: Path) -> Optional['InstalledApp']:
        """从 .desktop 文件解析"""
        try:
            content = path.read_text(encoding='utf-8')
            if '.local/share' not in content and '.local/bin' not in content:
                return None
            
            data = {'name': path.stem, 'filename': path.name, 'desktop_path': path}
            
            for line in content.split('\n'):
                if '=' not in line:
                    continue
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                
                if key == 'Name' and not data.get('name_set'):
                    data['name'] = value
                    data['name_set'] = True
                elif key == 'Icon':
                    data['icon'] = value
                elif key == 'Exec':
                    data['exec_cmd'] = value
                elif key == 'Comment':
                    data['comment'] = value
                elif key == 'Categories':
                    data['categories'] = value
                elif key == 'Terminal':
                    data['terminal'] = value.lower() == 'true'
            
            data.pop('name_set', None)
            return cls(**data)
        except Exception as e:
            logger.warning(f"解析 desktop 文件失败: {e}")
            return None
    
    def save(self):
        """保存到 .desktop 文件"""
        content = f"""[Desktop Entry]
Name={self.name}
Comment={self.comment}
Exec={self.exec_cmd}
Icon={self.icon}
Type=Application
Categories={self.categories}
Terminal={'true' if self.terminal else 'false'}
StartupNotify=false
"""
        self.desktop_path.write_text(content)
        
        # 更新桌面图标
        desktop_dir = Path.home() / '桌面'
        if not desktop_dir.exists():
            desktop_dir = Path.home() / 'Desktop'
        
        desktop_icon = desktop_dir / self.filename
        if desktop_icon.exists():
            desktop_icon.write_text(content)
            desktop_icon.chmod(0o755)
            subprocess.run(['gio', 'set', str(desktop_icon), 'metadata::trusted', 'true'],
                          capture_output=True)
        
        subprocess.run(['update-desktop-database', str(self.desktop_path.parent)],
                      capture_output=True)


# ============================================================================
# 应用编辑对话框
# ============================================================================

class AppEditDialog(Adw.Dialog):
    """应用编辑对话框"""
    
    def __init__(self, app: InstalledApp, parent: Gtk.Window, on_save: Callable):
        super().__init__()
        self.app = app
        self.parent_window = parent
        self.on_save_callback = on_save
        
        self.set_title(f"编辑 {app.name}")
        self.set_content_width(450)
        self.set_content_height(550)
        
        self._setup_ui()
    
    def _setup_ui(self):
        toolbar = Adw.ToolbarView()
        
        # 头部
        header = Adw.HeaderBar()
        header.add_css_class("flat")
        
        cancel_btn = Gtk.Button(label="取消")
        cancel_btn.connect("clicked", lambda _: self.close())
        header.pack_start(cancel_btn)
        
        save_btn = Gtk.Button(label="保存")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save)
        header.pack_end(save_btn)
        
        toolbar.add_top_bar(header)
        
        # 内容
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_start(16)
        content.set_margin_end(16)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        
        # 图标预览和选择
        icon_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        icon_box.set_halign(Gtk.Align.CENTER)
        
        self.icon_image = Gtk.Image()
        self.icon_image.set_pixel_size(96)
        self.icon_image.add_css_class("app-icon")
        self._update_icon_preview()
        icon_box.append(self.icon_image)
        
        icon_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        icon_btn_box.set_halign(Gtk.Align.CENTER)
        
        change_icon_btn = Gtk.Button(label="更换图标")
        change_icon_btn.add_css_class("pill")
        change_icon_btn.connect("clicked", self._on_change_icon)
        icon_btn_box.append(change_icon_btn)
        
        system_icon_btn = Gtk.Button(label="系统图标")
        system_icon_btn.add_css_class("pill")
        system_icon_btn.connect("clicked", self._on_system_icon)
        icon_btn_box.append(system_icon_btn)
        
        icon_box.append(icon_btn_box)
        content.append(icon_box)
        
        # 基本信息
        info_group = Adw.PreferencesGroup()
        info_group.set_title("基本信息")
        
        self.name_row = Adw.EntryRow()
        self.name_row.set_title("名称")
        self.name_row.set_text(self.app.name)
        info_group.add(self.name_row)
        
        self.comment_row = Adw.EntryRow()
        self.comment_row.set_title("描述")
        self.comment_row.set_text(self.app.comment)
        info_group.add(self.comment_row)
        
        self.categories_row = Adw.EntryRow()
        self.categories_row.set_title("分类")
        self.categories_row.set_text(self.app.categories)
        info_group.add(self.categories_row)
        
        content.append(info_group)
        
        # 执行设置
        exec_group = Adw.PreferencesGroup()
        exec_group.set_title("执行设置")
        
        self.exec_row = Adw.EntryRow()
        self.exec_row.set_title("执行命令")
        self.exec_row.set_text(self.app.exec_cmd)
        exec_group.add(self.exec_row)
        
        self.terminal_row = Adw.SwitchRow()
        self.terminal_row.set_title("在终端中运行")
        self.terminal_row.set_active(self.app.terminal)
        exec_group.add(self.terminal_row)
        
        content.append(exec_group)
        
        # 图标路径（高级）
        icon_group = Adw.PreferencesGroup()
        icon_group.set_title("图标设置")
        
        self.icon_row = Adw.EntryRow()
        self.icon_row.set_title("图标路径/名称")
        self.icon_row.set_text(self.app.icon)
        self.icon_row.connect("changed", lambda _: self._update_icon_preview())
        icon_group.add(self.icon_row)
        
        content.append(icon_group)
        
        # 文件位置
        file_group = Adw.PreferencesGroup()
        file_group.set_title("文件位置")
        
        file_row = Adw.ActionRow()
        file_row.set_title("Desktop 文件")
        file_row.set_subtitle(str(self.app.desktop_path))
        
        open_folder_btn = Gtk.Button(icon_name="folder-open-symbolic")
        open_folder_btn.set_valign(Gtk.Align.CENTER)
        open_folder_btn.add_css_class("flat")
        open_folder_btn.set_tooltip_text("打开所在文件夹")
        open_folder_btn.connect("clicked", self._on_open_folder)
        file_row.add_suffix(open_folder_btn)
        
        file_group.add(file_row)
        content.append(file_group)
        
        scroll.set_child(content)
        toolbar.set_content(scroll)
        self.set_child(toolbar)
    
    def _update_icon_preview(self):
        """更新图标预览"""
        icon = self.icon_row.get_text() if hasattr(self, 'icon_row') else self.app.icon
        
        if not icon:
            self.icon_image.set_from_icon_name("application-x-executable")
            return
        
        # 尝试作为文件路径
        if os.path.isfile(icon):
            try:
                self.icon_image.set_from_file(icon)
                return
            except:
                pass
        
        # 尝试作为图标名称
        self.icon_image.set_from_icon_name(icon)
    
    def _on_change_icon(self, btn):
        """选择图标文件"""
        dialog = Gtk.FileDialog()
        dialog.set_title("选择图标")
        
        filters = Gio.ListStore.new(Gtk.FileFilter)
        
        img_filter = Gtk.FileFilter()
        img_filter.set_name("图片文件")
        img_filter.add_mime_type("image/png")
        img_filter.add_mime_type("image/svg+xml")
        img_filter.add_mime_type("image/x-icon")
        img_filter.add_pattern("*.png")
        img_filter.add_pattern("*.svg")
        img_filter.add_pattern("*.ico")
        filters.append(img_filter)
        
        dialog.set_filters(filters)
        dialog.open(self.parent_window, None, self._on_icon_selected)
    
    def _on_icon_selected(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                path = file.get_path()
                # 复制到图标目录
                icons_dir = Path.home() / '.local' / 'share' / 'icons'
                icons_dir.mkdir(parents=True, exist_ok=True)
                
                app_name = self.app.name.lower().replace(' ', '-')
                dest = icons_dir / f"{app_name}{Path(path).suffix}"
                shutil.copy2(path, dest)
                
                self.icon_row.set_text(str(dest))
                self._update_icon_preview()
        except GLib.Error:
            pass
    
    def _on_system_icon(self, btn):
        """选择系统图标"""
        dialog = SystemIconDialog(self.parent_window, self._on_system_icon_selected)
        dialog.present(self.parent_window)
    
    def _on_system_icon_selected(self, icon_name: str):
        self.icon_row.set_text(icon_name)
        self._update_icon_preview()
    
    def _on_open_folder(self, btn):
        """打开文件夹"""
        subprocess.Popen(['xdg-open', str(self.app.desktop_path.parent)])
    
    def _on_save(self, btn):
        """保存更改"""
        self.app.name = self.name_row.get_text()
        self.app.comment = self.comment_row.get_text()
        self.app.categories = self.categories_row.get_text()
        self.app.exec_cmd = self.exec_row.get_text()
        self.app.terminal = self.terminal_row.get_active()
        self.app.icon = self.icon_row.get_text()
        
        self.app.save()
        self.on_save_callback()
        self.close()


# ============================================================================
# 系统图标选择对话框
# ============================================================================

class SystemIconDialog(Adw.Dialog):
    """系统图标选择对话框"""
    
    # 常用图标分类
    ICON_CATEGORIES = {
        "应用": [
            "application-x-executable", "utilities-terminal", "accessories-text-editor",
            "system-file-manager", "web-browser", "mail-client", "multimedia-player",
            "accessories-calculator", "preferences-system", "help-browser",
        ],
        "文件": [
            "folder", "folder-remote", "folder-download", "folder-documents",
            "folder-music", "folder-pictures", "folder-videos", "user-home",
            "network-server", "drive-harddisk",
        ],
        "网络": [
            "network-workgroup", "network-server", "network-wireless",
            "preferences-system-network", "web-browser", "mail-send",
        ],
        "开发": [
            "applications-development", "text-x-script", "text-x-generic",
            "package-x-generic", "system-run", "utilities-terminal",
        ],
        "多媒体": [
            "audio-x-generic", "video-x-generic", "image-x-generic",
            "camera-photo", "media-playback-start", "multimedia-player",
        ],
        "系统": [
            "preferences-system", "preferences-desktop", "system-settings",
            "emblem-system", "computer", "utilities-system-monitor",
        ],
    }
    
    def __init__(self, parent: Gtk.Window, on_select: Callable[[str], None]):
        super().__init__()
        self.on_select = on_select
        
        self.set_title("选择系统图标")
        self.set_content_width(500)
        self.set_content_height(450)
        
        self._setup_ui()
    
    def _setup_ui(self):
        toolbar = Adw.ToolbarView()
        
        header = Adw.HeaderBar()
        header.add_css_class("flat")
        toolbar.add_top_bar(header)
        
        # 搜索框
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("搜索图标...")
        self.search_entry.connect("search-changed", self._on_search)
        header.set_title_widget(self.search_entry)
        
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.content_box.set_margin_start(16)
        self.content_box.set_margin_end(16)
        self.content_box.set_margin_top(16)
        self.content_box.set_margin_bottom(16)
        
        self._load_icons()
        
        scroll.set_child(self.content_box)
        toolbar.set_content(scroll)
        self.set_child(toolbar)
    
    def _load_icons(self, filter_text: str = ""):
        """加载图标"""
        # 清空
        while child := self.content_box.get_first_child():
            self.content_box.remove(child)
        
        filter_text = filter_text.lower()
        
        for category, icons in self.ICON_CATEGORIES.items():
            filtered_icons = [i for i in icons if not filter_text or filter_text in i]
            if not filtered_icons:
                continue
            
            # 分类标题
            label = Gtk.Label(label=category)
            label.add_css_class("heading")
            label.set_halign(Gtk.Align.START)
            self.content_box.append(label)
            
            # 图标网格
            flow = Gtk.FlowBox()
            flow.set_selection_mode(Gtk.SelectionMode.NONE)
            flow.set_max_children_per_line(8)
            flow.set_min_children_per_line(4)
            flow.set_column_spacing(8)
            flow.set_row_spacing(8)
            
            for icon_name in filtered_icons:
                btn = Gtk.Button()
                btn.set_size_request(56, 56)
                btn.add_css_class("flat")
                btn.set_tooltip_text(icon_name)
                
                icon = Gtk.Image.new_from_icon_name(icon_name)
                icon.set_pixel_size(32)
                btn.set_child(icon)
                
                btn.connect("clicked", self._on_icon_clicked, icon_name)
                flow.append(btn)
            
            self.content_box.append(flow)
    
    def _on_search(self, entry):
        self._load_icons(entry.get_text())
    
    def _on_icon_clicked(self, btn, icon_name: str):
        self.on_select(icon_name)
        self.close()


# ============================================================================
# 已安装应用管理对话框
# ============================================================================

class InstalledAppsDialog(Adw.Dialog):
    """已安装应用管理对话框"""
    
    def __init__(self, installer: PackageInstaller, parent: Gtk.Window):
        super().__init__()
        self.installer = installer
        self.parent_window = parent
        self.apps: List[InstalledApp] = []
        
        self.set_title("应用管理")
        self.set_content_width(500)
        self.set_content_height(550)
        
        self._setup_ui()
        self._load_apps()
    
    def _setup_ui(self):
        toolbar = Adw.ToolbarView()
        
        header = Adw.HeaderBar()
        header.add_css_class("flat")
        
        # 刷新按钮
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.set_tooltip_text("刷新")
        refresh_btn.connect("clicked", lambda _: self._load_apps())
        header.pack_end(refresh_btn)
        
        toolbar.add_top_bar(header)
        
        # Toast 覆盖层
        self.toast_overlay = Adw.ToastOverlay()
        
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.add_css_class("boxed-list")
        self.listbox.set_margin_start(16)
        self.listbox.set_margin_end(16)
        self.listbox.set_margin_top(16)
        self.listbox.set_margin_bottom(16)
        
        scroll.set_child(self.listbox)
        self.toast_overlay.set_child(scroll)
        toolbar.set_content(self.toast_overlay)
        self.set_child(toolbar)
    
    def _load_apps(self):
        """加载已安装的应用"""
        # 清空列表
        while child := self.listbox.get_first_child():
            self.listbox.remove(child)
        
        self.apps = []
        apps_dir = Path.home() / '.local' / 'share' / 'applications'
        
        for desktop in apps_dir.glob('*.desktop'):
            app = InstalledApp.from_desktop_file(desktop)
            if app:
                self.apps.append(app)
        
        if not self.apps:
            empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            empty_box.set_valign(Gtk.Align.CENTER)
            empty_box.set_margin_top(48)
            empty_box.set_margin_bottom(48)
            
            icon = Gtk.Image.new_from_icon_name("package-x-generic-symbolic")
            icon.set_pixel_size(48)
            icon.add_css_class("dim-label")
            empty_box.append(icon)
            
            label = Gtk.Label(label="没有已安装的应用")
            label.add_css_class("dim-label")
            empty_box.append(label)
            
            self.listbox.append(empty_box)
            return
        
        for app in self.apps:
            row = self._create_app_row(app)
            self.listbox.append(row)
    
    def _create_app_row(self, app: InstalledApp) -> Adw.ActionRow:
        """创建应用行"""
        row = Adw.ActionRow()
        row.set_title(app.name)
        row.set_subtitle(app.comment or app.filename)
        row.set_activatable(True)
        row.connect("activated", self._on_edit, app)
        
        # 图标
        icon = Gtk.Image()
        icon.set_pixel_size(40)
        
        if app.icon:
            if os.path.isfile(app.icon):
                try:
                    icon.set_from_file(app.icon)
                except:
                    icon.set_from_icon_name(app.icon)
            else:
                icon.set_from_icon_name(app.icon)
        else:
            icon.set_from_icon_name("application-x-executable")
        
        row.add_prefix(icon)
        
        # 按钮组
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        btn_box.set_valign(Gtk.Align.CENTER)
        
        # 编辑按钮
        edit_btn = Gtk.Button(icon_name="document-edit-symbolic")
        edit_btn.add_css_class("flat")
        edit_btn.set_tooltip_text("编辑")
        edit_btn.connect("clicked", self._on_edit, app)
        btn_box.append(edit_btn)
        
        # 启动按钮
        launch_btn = Gtk.Button(icon_name="media-playback-start-symbolic")
        launch_btn.add_css_class("flat")
        launch_btn.set_tooltip_text("启动")
        launch_btn.connect("clicked", self._on_launch, app)
        btn_box.append(launch_btn)
        
        # 卸载按钮
        uninstall_btn = Gtk.Button(icon_name="user-trash-symbolic")
        uninstall_btn.add_css_class("flat")
        uninstall_btn.add_css_class("error")
        uninstall_btn.set_tooltip_text("卸载")
        uninstall_btn.connect("clicked", self._on_uninstall, app)
        btn_box.append(uninstall_btn)
        
        row.add_suffix(btn_box)
        
        # 箭头指示可点击
        arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
        arrow.add_css_class("dim-label")
        row.add_suffix(arrow)
        
        return row
    
    def _on_edit(self, widget, app: InstalledApp):
        """编辑应用"""
        dialog = AppEditDialog(app, self.parent_window, self._load_apps)
        dialog.present(self.parent_window)
    
    def _on_launch(self, btn, app: InstalledApp):
        """启动应用"""
        try:
            # 使用 gio launch
            subprocess.Popen(['gio', 'launch', str(app.desktop_path)], start_new_session=True)
        except Exception as e:
            self._show_toast(f"启动失败: {e}")
    
    def _on_uninstall(self, btn, app: InstalledApp):
        """卸载应用"""
        # 确认对话框
        dialog = Adw.AlertDialog()
        dialog.set_heading(f"卸载 {app.name}？")
        dialog.set_body("这将删除应用程序文件和桌面图标。")
        dialog.add_response("cancel", "取消")
        dialog.add_response("uninstall", "卸载")
        dialog.set_response_appearance("uninstall", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.connect("response", self._on_uninstall_response, app)
        dialog.present(self.parent_window)
    
    def _on_uninstall_response(self, dialog, response: str, app: InstalledApp):
        if response == "uninstall":
            self.installer.uninstall(app.name)
            self._load_apps()
            self._show_toast(f"{app.name} 已卸载")
    
    def _show_toast(self, message: str):
        toast = Adw.Toast(title=message)
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)


# ============================================================================
# 应用程序
# ============================================================================

class PackageInstallerApp(Adw.Application):
    """应用程序"""
    
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN
        )
        self.window = None
        self.installer = PackageInstaller()
    
    def do_startup(self):
        Adw.Application.do_startup(self)
        self._setup_actions()
    
    def _setup_actions(self):
        """设置应用动作"""
        installed_action = Gio.SimpleAction.new("installed", None)
        installed_action.connect("activate", self._on_show_installed)
        self.add_action(installed_action)
        
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about)
        self.add_action(about_action)
    
    def do_activate(self):
        if not self.window:
            self.window = InstallerWindow(self)
        self.window.present()
    
    def do_open(self, files, n_files, hint):
        self.do_activate()
        if files:
            path = files[0].get_path()
            if path and any(path.endswith(ext) for ext in ['.deb', '.tar.gz', '.tgz']):
                self.window._load_package(path)
    
    def _on_show_installed(self, action, param):
        if self.window:
            dialog = InstalledAppsDialog(self.installer, self.window)
            dialog.present(self.window)
    
    def _on_about(self, action, param):
        dialog = Adw.AboutDialog()
        dialog.set_application_name(APP_NAME)
        dialog.set_version(APP_VERSION)
        dialog.set_developer_name("Shiro")
        dialog.set_license_type(Gtk.License.MIT_X11)
        dialog.set_comments(
            "在 Fedora 上优雅地安装软件包\n\n"
            "支持 DEB 和 tar.gz 格式\n"
            "支持直接安装和 Distrobox 容器隔离"
        )
        dialog.set_website(APP_WEBSITE)
        dialog.set_application_icon("package-x-generic")
        dialog.set_developers(["Shiro"])
        dialog.set_copyright("© 2024 Shiro")
        
        if self.window:
            dialog.present(self.window)


# ============================================================================
# 入口点
# ============================================================================

def main():
    app = PackageInstallerApp()
    return app.run(None)


if __name__ == "__main__":
    main()
