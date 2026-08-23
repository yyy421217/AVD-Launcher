# Android 模拟器启动器

基于 tkinter 的 Android 模拟器（AVD）图形管理工具，零第三方依赖，提供完整的虚拟设备生命周期管理。

## 功能概览

### AVD 管理

- **列出设备**：自动扫描 AVD 目录，实时显示设备列表与运行状态（未运行 / 开机中 / 已开机）
- **三种启动模式**：正常启动、Fastboot 启动、Recovery 启动
- **添加 AVD**：
  - **Pixel 机型向导**：选择 Pixel 机型 + Android 版本，自动通过 `sdkmanager` 下载系统镜像并创建 AVD
  - **OTA 包导入**：导入 OTA zip 包，通过 sideload 刷入
  - **自定义镜像导入**：从目录或 zip 中导入 `system.img` 等镜像文件，自动检测并推断 API / Tag / ABI
- **备份与恢复**：将 AVD 完整打包为 zip（含 `.ini` 配置和 `.avd` 目录），支持一键恢复
- **删除 AVD**：通过 `avdmanager delete` 安全删除

### 模拟器运行时控制

- **窗口嵌入**：模拟器启动后自动嵌入启动器右侧面板，保持原始宽高比居中显示，支持拖动调整分区大小
- **虚拟按键面板**：悬浮置顶小窗口，发送电源 / 音量+ / 音量- 按键，支持电源长按，可附着到模拟器窗口
- **快照管理**：通过 `adb emu avd snapshot` 保存 / 加载 / 删除运行状态快照，横向卡片流展示
- **AVD 内部文件浏览**：通过 `adb shell ls` 浏览运行中模拟器的文件系统（`/sdcard`、`/data/local/tmp` 等），支持 `adb pull` 下载文件到本地

### Root 与调试

- **Root (adb)**：通过 `adb root` 获取临时 root 权限，自动 remount 可写分区
- **Root (Magisk)**：通过 rootAVD 脚本将 Magisk 注入 AVD 的 ramdisk，实现持久化 root
- **安装 APK**：通过 `adb install` 将 APK 安装到运行中的模拟器
- **关闭模拟器**：通过 `adb emu kill` 安全关闭指定 AVD

### 系统自检

- 启动时自动检测 `ANDROID_HOME` 和 SDK 组件（emulator / platform-tools / cmdline-tools）
- 缺失组件时可自动通过 `sdkmanager` 下载补齐

## 环境要求

| 组件 | 要求 |
|------|------|
| 操作系统 | Windows 10/11 |
| Python | 3.8+（需包含 tkinter） |
| Android SDK | 已安装或允许程序自动下载 |
| Git Bash | 仅 Magisk Root 功能需要（默认路径 `C:\Program Files\Git\bin\bash.exe`） |

> 程序零第三方 pip 依赖，仅需 Python 标准库 + tkinter。

## 快速开始

### 1. 配置 SDK 路径

编辑 `android_launcher.py` 第 25 行，将 `SDK_HOME` 改为你的 Android SDK 安装路径：

```python
SDK_HOME = r"D:\AndroidSdk"
```

### 2. 启动

双击 `启动模拟器.bat`，或在命令行运行：

```bash
python android_launcher.py
```

## 项目结构

```
.
├── android_launcher.py       # 主程序（4276 行）
├── 启动模拟器.bat             # Windows 启动脚本
├── app.ico                   # 应用图标
├── icon_512.png              # 图标预览
├── generate_icon.py          # 图标生成脚本（Pillow）
├── _launcher_out.log         # 运行时标准输出日志
├── _launcher_err.log         # 运行时错误日志
└── README.md
```

## 代码结构

| 类 / 模块 | 行号 | 职责 |
|-----------|------|------|
| `run_stream()` | L139 | 子进程执行，实时回传输出 |
| `list_avds()` | L160 | 扫描本地 AVD 列表 |
| `list_pixel_devices()` | L182 | 解析 Pixel 机型列表 |
| `list_available_system_images_online()` | L228 | 在线查询可用系统镜像 |
| `running_devices()` | L324 | 通过 `adb devices` 获取运行中设备 |
| `parse_snapshot_list()` | L388 | 解析快照列表输出 |
| `make_button()` | L515 | Material 风格圆角按钮（Canvas 自绘 + 阴影） |
| `make_card()` | L662 | Material 风格圆角卡片 |
| `AvdRow` | L716 | AVD 列表行（可展开，含状态 / 快捷按钮） |
| `AvdExpandableList` | L1011 | AVD 可展开列表容器 |
| `LauncherApp` | L1111 | 主窗口（顶栏 / AVD 列表 / 模拟器嵌入 / 日志） |
| `StartModeDialog` | L1998 | 启动模式选择对话框 |
| `PixelWizardDialog` | L2043 | Pixel 机型创建向导（180×180 版本卡片） |
| `OtaImportDialog` | L2525 | OTA 包导入对话框 |
| `CustomImageImportDialog` | L2638 | 自定义镜像导入对话框 |
| `SnapshotDialog` | L3228 | 快照管理对话框（横向卡片流） |
| `MagiskRootJob` | L3266 | Magisk Root 任务（下载 rootAVD.sh + Magisk APK） |
| `InternalFileBrowser` | L3550 | AVD 内部文件浏览器（adb ls / pull） |
| `AdbKeyPad` | L3879 | 虚拟按键悬浮面板（电源 / 音量） |

## 右键菜单

在 AVD 列表中右键单击设备，弹出操作菜单：

| 菜单项 | 功能 |
|--------|------|
| ▶ 正常启动 | 以默认模式启动 AVD |
| ⚡ Fastboot 启动 | 进入 Fastboot 模式 |
| 🛠 Recovery 启动 | 进入 Recovery 模式 |
| 📸 快照管理 | 打开快照管理窗口 |
| 🎛 虚拟按键面板 | 打开悬浮按键面板 |
| 🔑 Root (adb) | 临时 adb root |
| 🧩 Root (Magisk) | 持久化 Magisk root |
| 📦 安装 APK | 选择 APK 并安装 |
| 💾 备份 AVD | 打包为 zip 备份 |
| ♻ 恢复 AVD | 从 zip 备份恢复 |
| 📂 打开 AVD 目录 | 在资源管理器中打开 |
| 📁 AVD 内部文件（运行时） | 浏览模拟器内部文件系统 |
| ⚙ 打开配置文件 (.ini) | 打开 AVD 配置文件 |
| 🛑 关闭模拟器 | 关闭运行中的模拟器 |
| 🗑 删除 AVD | 删除虚拟设备 |

## 主题

采用 **Android Material Design 深色主题**，配色基于 Google 官方暗色色板：

| 层级 | 色值 | 用途 |
|------|------|------|
| 背景 | `#202124` | 页面底色 |
| 表面 | `#303134` | 卡片 / 菜单 / 输入框 |
| 顶栏 | `#28292C` | 标题栏 |
| 正文 | `#E8EAED` | 主文字 |
| 强调蓝 | `#8AB4F8` | 按钮 / 链接 / 选中 |
| 功能绿 | `#81C995` | 成功 / Root |
| 功能红 | `#F28B82` | 删除 / 关闭 |
| 功能黄 | `#FDD663` | 加载 / 开机中 |

所有颜色通过常量统一定义（L61-95），修改常量即可全局切换主题。

## 配置文件

启动器设置持久化在 `~/.android/launcher_settings.json`：

```json
{
  "avd_home": "C:\\Users\\<用户名>\\.android\\avd"
}
```

## 图标

图标通过 `generate_icon.py` 生成，设计元素：

- 圆角方形背景：Android 绿渐变（`#3DDC84` → `#0F9D58`）
- 上半部：白色 Android 机器人头部（半圆头 + 天线 + 深绿眼睛）
- 下半部：白色圆形播放按钮 + 深绿 ▶ 三角形

修改后重新运行即可生成：

```bash
python generate_icon.py
```

## 技术特点

- **零依赖**：纯 Python 标准库（tkinter / subprocess / json / threading），无需 pip install
- **Canvas 自绘 UI**：按钮和卡片通过 Canvas polygon + smooth 实现圆角，不依赖 ttk 主题
- **线程安全**：所有子进程操作在后台线程执行，通过 `self.after()` 回调更新 UI
- **窗口嵌入**：通过 Win32 API（`SetParent` / `SetWindowLong`）将模拟器窗口重定向到 tkinter Canvas，保持宽高比自适应缩放
- **状态轮询**：后台线程定期执行 `adb devices` 和 `getprop sys.boot_completed`，自动刷新 UI 状态
