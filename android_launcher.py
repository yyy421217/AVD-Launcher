# -*- coding: utf-8 -*-
"""Android 模拟器启动器 - 中文图形界面

基于 tkinter，零第三方依赖。
功能：
  - 列出 / 启动 / 关闭 AVD（正常 / Fastboot / Recovery 三种启动模式）
  - 添加 AVD：导入 OTA 包 sideload 刷入，或 Pixel 机型向导下载系统镜像
  - ADB 命令行交互（adb shell + keyevent 虚拟按键）
  - Root(adb) / Root(Magisk)
  - 安装 APK
  - 状态自动轮询（无需手动刷新）
  - 启动时自检：检测并下载缺失的 SDK 组件（emulator / platform-tools）
"""

import os
import re
import json
import time
import threading
import subprocess
import urllib.request
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ===== 启动器设置（持久化：AVD 安装路径、SDK 路径等） =====
SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".android", "launcher_settings.json")
_DEFAULT_AVD_HOME = os.path.join(os.path.expanduser("~"), ".android", "avd")


def load_settings():
    """读取设置文件，返回 dict"""
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(settings):
    """保存设置到文件"""
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ===== SDK 路径自动检测 (ANDROID_HOME) =====
def _is_valid_sdk(path):
    """判断目录是否像一个有效的 Android SDK 根目录"""
    if not path or not os.path.isdir(path):
        return False
    for sub in ("cmdline-tools", "emulator", "platform-tools", "system-images", "build-tools", "add-ons"):
        if os.path.isdir(os.path.join(path, sub)):
            return True
    return False


def detect_sdk_home():
    """自动检测 Android SDK (ANDROID_HOME) 位置。

    优先级：
      1. 已保存的设置 launcher_settings.json -> sdk_home
      2. 环境变量 ANDROID_HOME / ANDROID_SDK_ROOT
      3. Android Studio 默认安装位置及常见手动安装位置
      4. 回退到 D:\\AndroidSdk（保持向后兼容；自检对话框会引导补齐缺失组件）
    命中有效路径后持久化保存，避免下次重复探测。
    """
    settings = load_settings()
    saved = settings.get("sdk_home")
    if saved and _is_valid_sdk(saved):
        return saved

    candidates = []
    # 2. 环境变量
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        v = os.environ.get(var)
        if v:
            candidates.append(v)
    # 3 & 4. 常见默认位置（Android Studio 默认 + 常见手动安装盘符）
    local_app = os.environ.get("LOCALAPPDATA")
    userprofile = os.environ.get("USERPROFILE")
    common = [
        os.path.join(local_app, "Android", "Sdk") if local_app else None,
        os.path.join(userprofile, "AppData", "Local", "Android", "Sdk") if userprofile else None,
        r"C:\Android\Sdk",
        r"C:\AndroidSdk",
        r"D:\AndroidSdk",
        r"D:\Android\Sdk",
        r"E:\AndroidSdk",
        r"E:\Android\Sdk",
    ]
    candidates += [c for c in common if c]

    seen = set()
    for c in candidates:
        if not c or c in seen:
            continue
        seen.add(c)
        if _is_valid_sdk(c):
            settings["sdk_home"] = c
            save_settings(settings)
            return c

    # 5. 回退（即使无效也返回原默认值；自检对话框会引导补齐）
    return r"D:\AndroidSdk"


# ===== SDK 路径配置 =====
SDK_HOME = detect_sdk_home()
# 同步到环境变量，供子进程继承
os.environ["ANDROID_HOME"] = SDK_HOME
os.environ["ANDROID_SDK_ROOT"] = SDK_HOME
EMULATOR = os.path.join(SDK_HOME, "emulator", "emulator.exe")
ADB = os.path.join(SDK_HOME, "platform-tools", "adb.exe")
AVDMANAGER = os.path.join(SDK_HOME, "cmdline-tools", "latest", "bin", "avdmanager.bat")
SDKMANAGER = os.path.join(SDK_HOME, "cmdline-tools", "latest", "bin", "sdkmanager.bat")
ROOTAVD_DIR = os.path.join(SDK_HOME, "rootAVD")
GIT_BASH = r"C:\Program Files\Git\bin\bash.exe"

# 当前 AVD 安装路径（可由用户自定义）
AVD_USER_HOME = load_settings().get("avd_home", _DEFAULT_AVD_HOME)
os.environ["ANDROID_AVD_HOME"] = AVD_USER_HOME

# ===== 主题配色（Android Material Design 深色主题）=====
# 背景层级：BG（最深）→ CARD（表面）→ HEADER_BG（顶栏）
PRIMARY = "#8AB4F8"        # Google 暗色蓝（按钮、链接、选中强调）
PRIMARY_HV = "#AECBFA"     # 暗蓝悬停（更亮）
PRIMARY_CT = "#062E6F"     # 暗蓝按钮上的深色文字
PRIMARY_SOFT = "#1E3A5F"   # 暗蓝柔和底（Chip、选中行）
SUCCESS = "#81C995"        # Google 暗色绿（Root、成功状态）
SUCCESS_HV = "#A8DAB5"
SUCCESS_CT = "#06251A"
DANGER = "#F28B82"         # Google 暗色红（删除、关闭）
DANGER_HV = "#F6AEA9"
DANGER_CT = "#5A1A14"
WARN = "#FDD663"           # Google 暗色黄（加载/查找）
WARN_CT = "#3E2723"
GHOST_BG = "#303134"       # 幽灵按钮底（暗色表面）
GHOST_FG = "#E8EAED"       # 幽灵按钮前景（亮字）
GHOST_HV = "#3C4043"       # 幽灵按钮悬停
GHOST_BD = "#5F6368"       # 幽灵按钮描边
TEXT = "#E8EAED"           # 正文白（暗色模式主文字）
TEXT_SOFT = "#9AA0A6"      # 二级文字灰
MUTED = "#80868B"          # 注释灰
BG = "#202124"             # 页面底（Google 暗色背景）
CARD = "#303134"           # 卡片暗色表面
BORDER = "#3C4043"         # 暗色分隔灰
HEADER_BG = "#28292C"      # 顶栏底（略深于卡片，营造层次）
ACCENT = PRIMARY
ACCENT_HV = PRIMARY_HV
ACCENT_SOFT = PRIMARY_SOFT
LOG_BG = "#1A1A2E"         # 日志背景（更深沉）
LOG_FG = "#CDD6F4"

# 状态 Chip 暗色背景
CHIP_GREEN = "#1B3623"     # 已开机（暗绿底）
CHIP_YELLOW = "#3D2E0A"    # 开机中（暗琥珀底）
CHIP_GRAY = "#3C4043"      # 未运行（暗灰底）

CN = ("Microsoft YaHei UI", 10)
CN_BOLD = ("Microsoft YaHei UI", 11, "bold")
CN_TITLE = ("Microsoft YaHei UI", 14, "bold")
CN_SM = ("Microsoft YaHei UI", 9)
CN_MONO = ("Consolas", 9)

# Android 版本 -> API level 映射（用于 Pixel 向导显示）
ANDROID_VERSIONS = {
    21: "Android 5.0 Lollipop",
    22: "Android 5.1 Lollipop",
    23: "Android 6.0 Marshmallow",
    24: "Android 7.0 Nougat",
    25: "Android 7.1 Nougat",
    26: "Android 8.0 Oreo",
    27: "Android 8.1 Oreo",
    28: "Android 9 Pie",
    29: "Android 10",
    30: "Android 11",
    31: "Android 12",
    32: "Android 12L",
    33: "Android 13",
    34: "Android 14",
    35: "Android 15",
    36: "Android 16",
}

# Pixel 机型 -> 支持的 API 范围 (min_api, max_api)
PIXEL_API_RANGE = {
    "pixel": (25, 31), "pixel_xl": (25, 31),
    "pixel_2": (26, 32), "pixel_2_xl": (26, 32),
    "pixel_3": (28, 33), "pixel_3_xl": (28, 33),
    "pixel_3a": (28, 33), "pixel_3a_xl": (28, 33),
    "pixel_4": (29, 34), "pixel_4_xl": (29, 34),
    "pixel_4a": (29, 34),
    "pixel_5": (30, 34), "pixel_5a": (30, 34),
    "pixel_6": (31, 35), "pixel_6_pro": (31, 35),
    "pixel_6a": (32, 35),
    "pixel_7": (33, 35), "pixel_7_pro": (33, 35), "pixel_7a": (33, 35),
    "pixel_fold": (33, 35), "pixel_tablet": (33, 35),
    "pixel_8": (34, 36), "pixel_8_pro": (34, 36), "pixel_8a": (34, 36),
    "pixel_9": (34, 36), "pixel_9_pro": (34, 36),
    "pixel_9_pro_xl": (34, 36), "pixel_9_pro_fold": (34, 36),
}


# ============================================================
# 工具函数
# ============================================================
def run_stream(args, callback, env=None, cwd=None, timeout=None):
    """子进程运行命令，实时回传输出行。返回退出码。"""
    try:
        proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            shell=False, env=env, cwd=cwd,
            creationflags=subprocess.CREATE_NO_WINDOW)
        start = time.time()
        for raw in iter(proc.stdout.readline, b""):
            if timeout and time.time() - start > timeout:
                proc.kill()
                callback("[超时] 命令执行超过 %d 秒，已终止。" % timeout)
                return -1
            callback(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
        proc.wait()
        return proc.returncode
    except Exception as e:
        callback(f"[错误] {e}")
        return -1


def run_sdkmanager_install(pkgs, log_cb, env=None):
    """运行 sdkmanager 安装一个或多个包，自动接受许可，实时回传输出。

    pkgs: [pkg_id, ...] 例如 ["emulator", "platform-tools"]
    log_cb(line): 输出回调
    返回 [(pkg, code), ...]
    """
    if env is None:
        env = os.environ.copy()
        env["ANDROID_HOME"] = SDK_HOME
        env["ANDROID_SDK_ROOT"] = SDK_HOME

    def _run_one(args):
        try:
            proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE, shell=False, env=env,
                creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception as e:
            log_cb(f"[错误] 启动失败：{e}")
            return -1
        # 后台线程持续投喂 "y\n"，自动接受 sdkmanager 的许可提示
        stop = threading.Event()

        def feed():
            while not stop.is_set() and proc.poll() is None:
                try:
                    proc.stdin.write(b"y\n")
                    proc.stdin.flush()
                except Exception:
                    break
                time.sleep(0.15)

        feeder = threading.Thread(target=feed, daemon=True)
        feeder.start()
        for raw in iter(proc.stdout.readline, b""):
            log_cb(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
        proc.wait()
        stop.set()
        feeder.join(timeout=1)
        try:
            proc.stdin.close()
        except Exception:
            pass
        return proc.returncode

    results = []
    if not os.path.exists(SDKMANAGER):
        log_cb("[错误] sdkmanager 不存在，无法安装。")
        return [(pkg, -1) for pkg in pkgs]
    # 先统一接受所有许可，避免后续包安装卡在许可提示
    log_cb("$ sdkmanager --licenses")
    _run_one([SDKMANAGER, "--licenses"])
    for pkg in pkgs:
        log_cb(f'$ sdkmanager "{pkg}"')
        code = _run_one([SDKMANAGER, pkg])
        results.append((pkg, code))
    return results


def list_avds():
    """返回 [(name, path), ...]"""
    avds = []
    if os.path.exists(AVDMANAGER):
        try:
            out = subprocess.check_output(
                [AVDMANAGER, "list", "avd"],
                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW
            ).decode("utf-8", errors="replace")
            for m in re.finditer(r"Name:\s*(\S+).*?Path:\s*(\S+)", out, re.DOTALL):
                name, path = m.group(1).strip(), m.group(2).strip()
                if name and (name, path) not in avds:
                    avds.append((name, path))
        except Exception:
            pass
    if not avds and os.path.isdir(AVD_USER_HOME):
        for d in os.listdir(AVD_USER_HOME):
            if d.lower().endswith(".avd") and os.path.isdir(os.path.join(AVD_USER_HOME, d)):
                avds.append((d[:-4], os.path.join(AVD_USER_HOME, d)))
    return avds


def list_pixel_devices():
    """从 avdmanager 获取所有 Pixel 机型，返回 [(id, name), ...]"""
    profiles = []
    if os.path.exists(AVDMANAGER):
        try:
            out = subprocess.check_output(
                [AVDMANAGER, "list", "device"],
                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW
            ).decode("utf-8", errors="replace")
            cur_id = cur_name = None
            for line in out.splitlines():
                mi = re.match(r'\s*id\s*:\s*\d+\s+or\s+"([^"]+)"', line)
                if not mi:
                    mi = re.match(r'\s*id\s*:\s*"?([^\s"]+)"?', line)
                if mi:
                    cur_id = mi.group(1)
                mn = re.match(r"\s*Name\s*:\s*(.+)", line)
                if mn:
                    cur_name = mn.group(1).strip()
                if cur_id and cur_name:
                    if (cur_id, cur_name) not in profiles:
                        profiles.append((cur_id, cur_name))
                    cur_id = cur_name = None
        except Exception:
            pass
    return [(i, n) for (i, n) in profiles if "pixel" in i.lower()]


def system_image_installed(api):
    """检查 google_apis x86_64 系统镜像是否已安装"""
    return os.path.isdir(os.path.join(SDK_HOME, "system-images", f"android-{api}", "google_apis", "x86_64"))


def list_installed_images():
    """返回已安装的 API level 集合"""
    apis = set()
    base = os.path.join(SDK_HOME, "system-images")
    if os.path.isdir(base):
        for api in os.listdir(base):
            if os.path.isdir(os.path.join(base, api, "google_apis", "x86_64")):
                m = re.match(r"android-(\d+)", api)
                if m:
                    apis.add(int(m.group(1)))
    return apis


def list_available_system_images_online(timeout=60):
    """调用 sdkmanager --list 获取官方提供的全部 system-images（google_apis x86_64）。

    返回 (apis: set[int], pkgs: dict[api -> pkg_id])
    通过 SDK manager 在线通道检查最新 Android 版本，比本地硬编码 ANDROID_VERSIONS 更新。
    """
    apis = set()
    pkgs = {}
    if not os.path.exists(SDKMANAGER):
        return apis, pkgs
    env = os.environ.copy()
    env["ANDROID_HOME"] = SDK_HOME
    env["ANDROID_SDK_ROOT"] = SDK_HOME
    # 不同 sdkmanager 版本参数命名有差异，按优先级 fallback
    candidates = [
        [SDKMANAGER, "--list", "--channel=0"],
        [SDKMANAGER, "--list"],
    ]
    out = ""
    for args in candidates:
        try:
            proc = subprocess.run(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            text = proc.stdout.decode("utf-8", errors="replace")
            if "Available Packages" in text or "Installed Packages" in text:
                out = text
                break
        except Exception:
            continue
    # sdkmanager --list 输出段落："Available Packages:" -> package path
    in_section = False
    for raw in out.splitlines():
        line = raw.strip()
        if line.startswith("Available Packages"):
            in_section = True
            continue
        if line.startswith("Installed Packages") or line.startswith("Available Updates"):
            in_section = False
            continue
        if not in_section or not line:
            continue
        # 第 1 列是 package id，形如 system-images;android-35;google_apis;x86_64
        fields = line.split()
        if not fields:
            continue
        pkg = fields[0]
        parts = pkg.split(";")
        if len(parts) == 4 and parts[0] == "system-images" and parts[2] == "google_apis" and parts[3] == "x86_64":
            m = re.match(r"android-(\d+)", parts[1])
            if m:
                api = int(m.group(1))
                apis.add(api)
                pkgs[api] = pkg
    return apis, pkgs


def refresh_android_version_labels(extra_apis):
    """根据在线检查得到的新 API level 自动扩充 ANDROID_VERSIONS 的标签。

    对于本地表中缺失的 API，生成合理的 "Android N" 风格名称（数字递增）。
    返回新建的 {api: label} 字典，调用方合并到显示逻辑。
    """
    new_labels = {}
    if not extra_apis:
        return new_labels
    # 已知最大编号
    max_known_num = 0
    for api, label in ANDROID_VERSIONS.items():
        m = re.search(r"Android\s+(\d+)", label)
        if m:
            num = int(m.group(1))
            if num > max_known_num:
                max_known_num = num
    existing_nums = {}
    for api, label in ANDROID_VERSIONS.items():
        m = re.search(r"Android\s+(\d+)", label)
        if m:
            existing_nums[int(m.group(1))] = api
    for api in sorted(extra_apis):
        if api in ANDROID_VERSIONS:
            continue
        # 从 15+ API 开始，API = Release+10 大致对应
        guess_num = max(max_known_num + 1, api - 20)
        while guess_num in existing_nums:
            guess_num += 1
        label = f"Android {guess_num}"
        new_labels[api] = label
        existing_nums[guess_num] = api
        if guess_num > max_known_num:
            max_known_num = guess_num
    return new_labels


def running_devices():
    """返回 [serial, ...] 在线的 emulator"""
    devices = []
    if not os.path.exists(ADB):
        return devices
    try:
        out = subprocess.check_output(
            [ADB, "devices"], stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW
        ).decode("utf-8", errors="replace")
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) == 2 and parts[0].startswith("emulator-") and parts[1] in ("device", "offline"):
                devices.append((parts[0], parts[1]))
    except Exception:
        pass
    return devices


def boot_completed(serial):
    if not os.path.exists(ADB):
        return "?"
    try:
        return subprocess.check_output(
            [ADB, "-s", serial, "shell", "getprop", "sys.boot_completed"],
            stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW
        ).decode("utf-8", errors="replace").strip()
    except Exception:
        return "?"


def running_avd_map():
    """返回 {avd_name: "booted"/"booting"}，通过 `adb emu avd name` 获取每个运行中模拟器对应的 AVD 名。

    同时返回 {avd_name: serial} 用于后续操作。
    """
    result = {}   # name -> status
    serials = {}  # name -> serial
    for serial, state in running_devices():
        if state != "device":
            continue
        name = None
        try:
            out = subprocess.check_output(
                [ADB, "-s", serial, "emu", "avd", "name"],
                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW
            ).decode("utf-8", errors="replace").strip()
            # 输出可能含多行，取第一行非空且非 OK 的
            for line in out.splitlines():
                line = line.strip()
                if line and line != "OK":
                    name = line
                    break
        except Exception:
            name = None
        if not name:
            continue
        bc = boot_completed(serial)
        status = "booted" if bc == "1" else "booting"
        result[name] = status
        serials[name] = serial
    return result, serials


def parse_snapshot_list(text):
    """解析 `adb emu avd snapshot list` 输出，返回 [(name, size, date), ...]。

    emulator 实际输出格式：
        List of snapshots present on all disks:
        ID        TAG                 VM SIZE                DATE       VM CLOCK
        --        default_boot            68M 2026-08-22 23:29:08   00:02:40.870
        --        snap_test_001           68M 2026-08-22 23:39:39   00:02:49.714
        OK
    名称在 TAG 列，大小格式如 68M / 1.2G。
    """
    snapshots = []
    started = False
    for line in text.splitlines():
        s = line.rstrip()
        if not s.strip():
            continue
        # 表头：含 TAG 和 DATE
        if "TAG" in s and "DATE" in s:
            started = True
            continue
        if not started:
            continue
        # 跳过分隔行
        if s.strip().startswith("---") or s.strip().startswith("==="):
            continue
        # 跳过 OK 结尾
        if s.strip() == "OK":
            continue
        # 真实行格式: -- <tag> <size> <date> <vm_clock>
        # size 格式: 68M / 1.2G / 456K
        m = re.match(
            r"^(--|\S+)\s+(\S+)\s+(\d+(?:\.\d+)?[GMK])\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})",
            s)
        if m:
            snapshots.append((m.group(2).strip(), m.group(3).strip(), m.group(4).strip()))
    return snapshots


def adb_root_status(serial):
    """检查设备是否已 root，返回 (is_root, detail)"""
    if not os.path.exists(ADB):
        return (False, "adb 不存在")
    try:
        out = subprocess.check_output(
            [ADB, "-s", serial, "shell", "id"],
            stderr=subprocess.STDOUT, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW
        ).decode("utf-8", errors="replace").strip()
        if "uid=0" in out:
            return (True, out)
        return (False, out)
    except subprocess.TimeoutExpired:
        return (False, "超时")
    except Exception as e:
        return (False, str(e))


def win_to_bash_path(p):
    p = p.replace("\\", "/")
    m = re.match(r"([A-Za-z]):/?(.*)", p)
    if m:
        return "/" + m.group(1).lower() + "/" + m.group(2)
    return p


def ensure_downloaded(url, dest, log=None):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        if log:
            log(f"已存在：{dest}")
        return True
    if log:
        log(f"下载中：{url}")
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
            f.write(r.read())
        if log:
            log(f"下载完成：{dest}（{os.path.getsize(dest) // 1024} KB）")
        return True
    except Exception as e:
        if log:
            log(f"[下载失败] {e}")
        return False


def latest_magisk_apk_url(log=None):
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/topjohnwu/Magisk/releases/latest",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
        for a in data.get("assets", []):
            if a.get("name", "").lower().endswith(".apk"):
                if log:
                    log(f"最新 Magisk：{a['name']} ({data.get('tag_name', '?')})")
                return a["browser_download_url"]
        tag = data.get("tag_name", "")
        if tag:
            return f"https://github.com/topjohnwu/Magisk/releases/download/{tag}/Magisk-{tag}.apk"
    except Exception as e:
        if log:
            log(f"[获取 Magisk 版本失败] {e}")
    return None


# ============================================================
# UI 组件
# ============================================================
def _mix(c1, c2, t):
    """混合两个 #RRGGBB 颜色（t=0 全 c1，t=1 全 c2）"""
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def make_button(parent, text, command, style="primary", padx=18, pady=8, radius=12):
    """Material 风格圆角按钮（Canvas 自绘，含阴影），与 Google Android 官网一致。

    style: primary / danger / success / ghost
    """
    # 兼容旧版 radius<8 时按 12 处理，使圆角更明显；显式传入大半径时保留
    if radius is not None and radius < 8:
        radius = 12
    # 样式色板
    style_map = {
        "primary": {
            "fill": PRIMARY, "hover": PRIMARY_HV, "fg": PRIMARY_CT,
            "shadow": _mix(PRIMARY, "#000000", 0.18),
            "bd": None,
        },
        "danger": {
            "fill": DANGER, "hover": DANGER_HV, "fg": DANGER_CT,
            "shadow": _mix(DANGER, "#000000", 0.18),
            "bd": None,
        },
        "success": {
            "fill": SUCCESS, "hover": SUCCESS_HV, "fg": SUCCESS_CT,
            "shadow": _mix(SUCCESS, "#000000", 0.18),
            "bd": None,
        },
        "ghost": {
            "fill": GHOST_BG, "hover": GHOST_HV, "fg": GHOST_FG,
            "shadow": "#00000000",
            "bd": GHOST_BD,
        },
    }
    st = style_map.get(style, style_map["primary"])

    # 按钮字体：主/成功/危险用粗体，幽灵按钮用常规
    font_tuple = CN_BOLD if style != "ghost" else CN
    # 测字大小（用 tk font 测量，不受 widget map 状态影响）
    from tkinter import font as _tkfont
    ff, fs, *rest = font_tuple
    bold_flag = ("bold" in rest) or (style != "ghost")
    font_obj = _tkfont.Font(family=ff, size=fs, weight=("bold" if bold_flag else "normal"))
    tw = font_obj.measure(text)
    th = font_obj.metrics("linespace")
    w = max(60, tw + padx * 2)
    h = max(32, th + pady * 2)

    pad_shadow = 2
    canvas_w = w + pad_shadow * 2
    canvas_h = h + pad_shadow * 2
    c = tk.Canvas(parent, width=canvas_w, height=canvas_h,
                   bg=parent.cget("bg") if parent.cget("bg") else BG,
                   highlightthickness=0, bd=0, cursor="hand2")

    def _draw(fill_color, y_off=1):
        c.delete("all")
        x1 = pad_shadow
        y1 = pad_shadow + y_off
        x2 = pad_shadow + w
        y2 = pad_shadow + h + y_off
        r = radius
        # Material 风格：下方 1~2px 阴影
        if st.get("shadow") and st["shadow"] != "#00000000":
            c.create_rectangle(x1, y2 - 3, x2, y2 + 2, outline="", fill=st["shadow"])
        # 主体圆角矩形
        def rr(cv, x1, y1, x2, y2, r, fill, outline=None, width=1):
            points = [
                x1 + r, y1, x2 - r, y1,
                x2, y1, x2, y1 + r,
                x2, y2 - r, x2, y2,
                x2 - r, y2, x1 + r, y2,
                x1, y2, x1, y2 - r,
                x1, y1 + r, x1, y1,
            ]
            return cv.create_polygon(points, fill=fill, outline=outline,
                                     width=width, smooth=True, splinesteps=24)
        if st.get("bd"):
            rr(c, x1, y1, x2, y2, r, fill_color, outline=st["bd"], width=1)
        else:
            rr(c, x1, y1, x2, y2, r, fill_color)
        # 文字居中
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        c.create_text(cx, cy, text=text, fill=st["fg"], font=font_tuple)

    def on_enter(e):
        _draw(st["hover"], y_off=1)

    def on_leave(e):
        _draw(st["fill"], y_off=0)

    def on_press(e):
        _draw(st["hover"], y_off=2)

    def on_release(e):
        _draw(st["hover"], y_off=1)
        # 点击触发命令：优先用 e.x / e.y（画布相对坐标），这在 PanedWindow / Canvas create_window 等
        # 复杂嵌套布局下比 winfo_rootx 减差更准确、不会出现"命中偏差导致按钮点不动"。
        x_rel = getattr(e, "x", None)
        y_rel = getattr(e, "y", None)
        inside = False
        if isinstance(x_rel, int) and isinstance(y_rel, int):
            inside = (0 <= x_rel <= canvas_w and 0 <= y_rel <= canvas_h)
        else:
            # fallback 到 root 坐标差（某些 tk 事件对象不带 x）
            x0, y0 = e.x_root, e.y_root
            mx, my = c.winfo_rootx(), c.winfo_rooty()
            inside = (0 <= (x0 - mx) <= canvas_w and 0 <= (y0 - my) <= canvas_h)
        if inside:
            try:
                command()
            except Exception as err:
                print("button cmd error:", err)

    c.bind("<Enter>", on_enter)
    c.bind("<Leave>", on_leave)
    c.bind("<Button-1>", on_press)
    c.bind("<ButtonRelease-1>", on_release)

    # 初始绘制
    on_leave(None)

    # 封装：暴露 pack/grid 等几何管理器方法 + config(text)
    class Btn:
        def __init__(self, canvas, on_update):
            self._c = canvas
            self._up = on_update
            self.pack = self._c.pack
            self.pack_forget = self._c.pack_forget
            self.grid = self._c.grid
            self.grid_forget = self._c.grid_forget
            self.place = self._c.place
            self.bind = self._c.bind
            self.winfo_width = self._c.winfo_width
            self.winfo_height = self._c.winfo_height
            self.destroy = self._c.destroy
            self.configure = self.config
        def config(self, text=None, **kw):
            if text is not None:
                self._up(text)
            return self._c.configure(**kw)
    def upd_text(new_text):
        nonlocal text
        text = new_text
        on_leave(None)
    c._btn = Btn(c, upd_text)
    return c


def make_link(parent, text, url, font=None, bg=None):
    """创建可点击的链接 Label，点击后用默认浏览器打开 url。"""
    if font is None:
        font = CN_SM
    if bg is None:
        bg = parent.cget("bg") or BG

    def _open(_e=None):
        try:
            webbrowser.open(url)
        except Exception:
            pass

    lbl = tk.Label(parent, text=text, bg=bg, fg=ACCENT, font=font,
                   cursor="hand2", activeforeground=PRIMARY_HV)
    lbl.bind("<Button-1>", _open)
    return lbl


def make_card(parent, padx=18, pady=16, radius=14, bg=None, bd_color=None):
    """Google 风格圆角卡片：Canvas 自绘圆角矩形 + 细描边 + 内边距。

    返回的是一个 Frame（可直接用于 PanedWindow.add / pack / grid），
    并在其上挂有：
      - card._inner  : 放置子控件的内部 Frame
      - card._padx / card._pady
    使用 pack_card(card) 可直接拿到内部 Frame。
    """
    bg = bg or CARD
    bd_color = bd_color or BORDER
    outer_bg = parent.cget("bg") if parent and parent.cget("bg") else BG
    outer = tk.Frame(parent, bg=outer_bg, highlightthickness=0, bd=0)
    canvas = tk.Canvas(outer, bg=outer_bg, highlightthickness=0, bd=0)
    canvas.pack(fill="both", expand=True)
    inner = tk.Frame(outer, bg=bg, bd=0, highlightthickness=0)

    def _redraw(_=None):
        w = max(1, outer.winfo_width())
        h = max(1, outer.winfo_height())
        canvas.delete("all")
        x1, y1, x2, y2 = 0.5, 0.5, w - 0.5, h - 0.5
        r = min(radius, (x2 - x1) / 2, (y2 - y1) / 2)
        pts = [
            x1 + r, y1, x2 - r, y1,
            x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r,
            x1, y1 + r, x1, y1,
        ]
        canvas.create_polygon(pts, fill=bg, outline=bd_color, width=1,
                              smooth=True, splinesteps=30)
        inner.place(x=1 + padx, y=1 + pady,
                    width=max(0, w - 2 - 2 * padx),
                    height=max(0, h - 2 - 2 * pady))

    outer.bind("<Configure>", _redraw)
    outer._inner = inner
    outer._padx = padx
    outer._pady = pady
    outer._radius = radius
    return outer


def pack_card(card):
    """展开卡片：pack 并返回内部 Frame。"""
    card.pack(fill="both", expand=True)
    return card._inner


# ============================================================
# AVD 可展开列表（每台 AVD 一行，点击展开状态与快捷操作）
# ============================================================
class AvdRow(tk.Frame):
    """单行 AVD 可展开栏：
    行头：展开箭头 + 状态点 + AVD 名 + 路径摘要
    展开体：状态/root/serial/路径 + 快捷按钮
    """

    ROW_BG = CARD
    ROW_BG_ALT = "#28292C"
    ROW_SEL = PRIMARY_SOFT
    ROW_BD = BORDER

    def __init__(self, master, avd_name, avd_path, status, app_ref,
                 on_select=None, on_context=None, on_start=None, on_start_fastboot=None,
                 on_start_recovery=None, on_root=None, on_backup=None, on_restore=None,
                 on_snapshot=None, on_internal_files=None, on_delete=None, on_kill=None,
                 on_open_folder=None, on_open_config=None, row_index=0):
        self.avd_name = avd_name
        self.avd_path = avd_path
        self.status = status  # booted / booting / stopped
        self.app = app_ref
        self.on_select_cb = on_select
        self.on_context_cb = on_context
        self._root_cache = None  # (bool, str) 缓存，避免每行每秒调 adb
        self._info_cache = {}  # serial / abi / size / model 等
        self._expanded = False
        super().__init__(master, bg=ROW_BG_ALT if row_index % 2 else self.ROW_BG,
                         highlightthickness=0, bd=0)

        self._row_bg = ROW_BG_ALT if row_index % 2 else self.ROW_BG

        # 顶部行（可点击）
        top = tk.Frame(self, bg=self._row_bg, bd=0, highlightthickness=0)
        top.pack(fill="x")

        self.arrow = tk.Label(top, text="▶", bg=self._row_bg, fg=MUTED,
                              font=("Segoe UI", 9), width=2, padx=2, cursor="hand2")
        self.arrow.pack(side="left", padx=(8, 4))
        self.arrow.bind("<Button-1>", lambda e: self.toggle())

        self.dot = tk.Label(top, text="·", bg=self._row_bg, fg=TEXT,
                            font=("Segoe UI Emoji", 14, "bold"), width=2, padx=2)
        self.dot.pack(side="left")

        self.name_lbl = tk.Label(top, text=avd_name, bg=self._row_bg, fg=TEXT,
                                 font=("Microsoft YaHei UI", 10, "bold"),
                                 anchor="w", padx=6, cursor="hand2")
        self.name_lbl.pack(side="left", fill="x", expand=True)

        self.state_chip = tk.Label(top, text=self._state_txt(), bg=self._state_chip_bg(),
                                   fg=self._state_chip_fg(),
                                   font=CN_SM, padx=10, pady=2,
                                   highlightbackground=self.ROW_BD, highlightthickness=1)
        self.state_chip.pack(side="right", padx=(0, 8))

        # 展开面板（默认隐藏）
        self.body = tk.Frame(self, bg=self._row_bg, bd=0, highlightthickness=0)

        # 行头点击事件绑定（选中 + 切换展开/收起）
        for w in (top, self.name_lbl, self.dot):
            w.bind("<Button-1>", self._on_row_click)
            w.bind("<Double-Button-1>", lambda e: self.toggle())
            w.bind("<Button-3>", self._on_row_right)

        self._set_status_icons()

    # ---------- 状态 ----------
    def _state_txt(self):
        if self.status == "booted":
            return "已开机"
        if self.status == "booting":
            return "开机中"
        return "未运行"

    def _state_chip_bg(self):
        if self.status == "booted":
            return CHIP_GREEN
        if self.status == "booting":
            return CHIP_YELLOW
        return CHIP_GRAY

    def _state_chip_fg(self):
        if self.status == "booted":
            return SUCCESS
        if self.status == "booting":
            return WARN
        return MUTED

    def _set_status_icons(self):
        if self.status == "booted":
            self.dot.config(text="🟢", fg=SUCCESS)
        elif self.status == "booting":
            self.dot.config(text="🟡", fg=WARN)
        else:
            self.dot.config(text="⚪", fg=MUTED)
        self.state_chip.config(text=self._state_txt(),
                               bg=self._state_chip_bg(),
                               fg=self._state_chip_fg())

    def update_status(self, new_status):
        changed = new_status != self.status
        self.status = new_status
        self._set_status_icons()
        # 状态变化时刷新展开面板（若已展开）
        if changed and self._expanded:
            self._rebuild_body()

    def _on_row_click(self, _evt):
        if self.on_select_cb:
            self.on_select_cb(self)
        # 选中样式
        try:
            for w in (self, self.arrow, self.dot, self.name_lbl):
                w.config(bg=self.ROW_SEL)
            self.state_chip.config(bg=self.ROW_SEL)
        except Exception:
            pass

    def _on_row_right(self, evt):
        if self.on_context_cb:
            self.on_context_cb(self, evt)

    def clear_selection_style(self):
        for w in (self, self.arrow, self.dot, self.name_lbl):
            try:
                w.config(bg=self._row_bg)
            except Exception:
                pass
        self.state_chip.config(bg=self._state_chip_bg())

    # ---------- 展开/收起 ----------
    def toggle(self, expand=None):
        self._expanded = not self._expanded if expand is None else bool(expand)
        if self._expanded:
            self.arrow.config(text="▼")
            self.body.pack(fill="x", pady=(0, 10), padx=(36, 14))
            self._rebuild_body()
        else:
            self.arrow.config(text="▶")
            try:
                self.body.pack_forget()
            except Exception:
                pass

    def _rebuild_body(self):
        for w in self.body.winfo_children():
            w.destroy()

        # 信息网格
        info = tk.Frame(self.body, bg=self._row_bg)
        info.pack(fill="x")

        # 异步补充详情（root/serial/size），避免卡顿
        self._info_line(info, "📂 存储路径", self.avd_path, row=0)
        self._info_line(info, "🚀 运行状态", self._state_txt(), row=1)

        serial = self._info_cache.get("serial") or (self.app._avd_serials.get(self.avd_name) if hasattr(self.app, "_avd_serials") else None)
        if serial:
            self._info_cache["serial"] = serial
            self._info_line(info, "🔌 ADB Serial", serial, row=2)
        else:
            self._info_line(info, "🔌 ADB Serial", "— 未开机 —", row=2, mute=True)

        # Root 信息（booted 时尝试检测并展示，其余显示 N/A）
        root_txt = "— 未开机 —"
        root_fg = MUTED
        if self.status == "booted":
            cache = self._root_cache
            if cache is None:
                root_txt = "检测中…"
                root_fg = WARN
                # 后台检测
                serial_for_root = serial
                threading.Thread(target=self._bg_check_root, args=(serial_for_root,),
                                 daemon=True).start()
            else:
                ok, detail = cache
                root_txt = ("已 Root  · " + detail) if ok else ("未 Root  · " + detail)
                root_fg = SUCCESS if ok else MUTED
        self._info_line(info, "🔐 Root 状态", root_txt, row=3, fg=root_fg)

        # 额外信息（异步：model/abi/size）
        self._info_line(info, "📱 机型 / ABI / 分辨率", "加载中…", row=4, key="extra", mute=True)
        if self.status == "booted" and not self._info_cache.get("extra_done"):
            serial_ex = serial
            threading.Thread(target=self._bg_fetch_extra, args=(serial_ex,), daemon=True).start()
        elif self._info_cache.get("extra_done"):
            self._set_info_line(info, "extra", self._info_cache.get("extra_txt", "—"),
                                row=4)

        # 快捷操作按钮行
        btns = tk.Frame(self.body, bg=self._row_bg)
        btns.pack(fill="x", pady=(10, 0))

        # 启动三选一（未开机才显示；已开机显示"关闭"）
        if self.status != "booted" and self.status != "booting":
            if hasattr(self, "_s_b"): return
            self._mk(btns, "▶ 正常启动", "primary", lambda n=self.avd_name: self.app.start_avd(n, "normal"))
            self._mk(btns, "⚡ Fastboot", "ghost", lambda n=self.avd_name: self.app.start_avd(n, "fastboot"))
            self._mk(btns, "🛠  Recovery", "ghost", lambda n=self.avd_name: self.app.start_avd(n, "recovery"))
        else:
            self._mk(btns, "🛑 关闭模拟器", "danger", lambda n=self.avd_name: self.app.kill_emulator_for(n))

        self._mk(btns, "🔑 Root(adb)", "ghost", lambda: self.app.root_avd_gui(self.avd_name))
        self._mk(btns, "💾 备份", "ghost", lambda: self.app.backup_avd_for(self.avd_name))
        self._mk(btns, "♻  恢复", "ghost", lambda: self.app.restore_avd_for(self.avd_name))
        self._mk(btns, "📸 快照", "ghost", lambda: self.app.snapshot_avd_for(self.avd_name))
        self._mk(btns, "📁 内部文件", "ghost", lambda: self.app.internal_for(self.avd_name))
        self._mk(btns, "📂 打开目录", "ghost", lambda: self.app.open_folder_for(self.avd_name))
        self._mk(btns, "🗑  删除", "ghost", lambda: self.app.delete_avd_for(self.avd_name))

    def _mk(self, parent, text, style, cmd):
        b = make_button(parent, text, cmd, style, padx=12, pady=5, radius=10)
        b.pack(side="left", padx=(0, 8), pady=2)
        return b

    def _info_line(self, parent, k, v, row, fg=None, mute=False, key=None):
        fg = fg or (MUTED if mute else TEXT)
        a = tk.Label(parent, text=k, bg=self._row_bg, fg=MUTED, font=CN_SM, anchor="w",
                     width=18)
        a.grid(row=row, column=0, sticky="w", padx=(0, 8), pady=1)
        b = tk.Label(parent, text=v, bg=self._row_bg, fg=fg, font=CN_SM, anchor="w",
                     wraplength=560, justify="left")
        b.grid(row=row, column=1, sticky="w", pady=1)
        if key:
            if not hasattr(self, "_info_widgets"):
                self._info_widgets = {}
            self._info_widgets[key] = (a, b)

    def _set_info_line(self, parent, key, new_value, row=None, fg=None):
        if not hasattr(self, "_info_widgets") or key not in self._info_widgets:
            return
        _a, b = self._info_widgets[key]
        b.config(text=new_value, fg=(fg or TEXT))

    # ---------- 异步后台任务 ----------
    def _bg_check_root(self, serial):
        if not serial:
            self._root_cache = (False, "未找到 serial")
        else:
            try:
                self._root_cache = adb_root_status(serial)
            except Exception as e:
                self._root_cache = (False, f"检测失败：{e}")
        self.after(0, lambda: self._expanded and self._rebuild_body())

    def _bg_fetch_extra(self, serial):
        if not serial:
            return
        parts = []
        # ABI
        try:
            code, out = self._run([ADB, "-s", serial, "shell", "getprop", "ro.product.cpu.abi"])
            if code == 0 and out.strip():
                parts.append(out.strip())
        except Exception:
            pass
        # Model
        try:
            code, out = self._run([ADB, "-s", serial, "shell", "getprop", "ro.product.model"])
            if code == 0 and out.strip():
                parts.insert(0, out.strip())
        except Exception:
            pass
        # wm size
        try:
            code, out = self._run([ADB, "-s", serial, "shell", "wm", "size"])
            if code == 0 and "Physical size:" in out:
                s = [ln.split(":", 1)[1].strip() for ln in out.splitlines() if "Physical size:" in ln]
                if s:
                    parts.append(s[0])
        except Exception:
            pass
        # Android version
        try:
            code, out = self._run([ADB, "-s", serial, "shell", "getprop", "ro.build.version.release"])
            if code == 0 and out.strip():
                parts.append("Android " + out.strip())
        except Exception:
            pass
        txt = "  ·  ".join(parts) if parts else "—"
        self._info_cache["extra_txt"] = txt
        self._info_cache["extra_done"] = True
        self.after(0, lambda: self._expanded and self._rebuild_body())

    @staticmethod
    def _run(args, timeout=15):
        try:
            proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  timeout=timeout,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return proc.returncode, proc.stdout.decode("utf-8", errors="replace")
        except Exception as e:
            return -1, str(e)


class AvdExpandableList(tk.Frame):
    """支持滚动、单选、右键菜单、每行可展开的 AVD 列表组件。"""

    def __init__(self, master, app_ref, callbacks):
        super().__init__(master, bg=CARD, highlightthickness=0, bd=0)
        self.app = app_ref
        self.cb = callbacks  # {on_select, on_context, empty_hint?}
        self.rows = []  # [AvdRow,...]
        self.selected = None  # AvdRow
        self._empty = None

        # 滚动条 + 画布 + 容器
        self.sb = ttk.Scrollbar(self, orient="vertical")
        self.sb.pack(side="right", fill="y")
        self.canvas = tk.Canvas(self, bg=CARD, highlightthickness=0, bd=0,
                                yscrollcommand=self.sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.sb.config(command=self.canvas.yview)
        self.container = tk.Frame(self.canvas, bg=CARD, bd=0, highlightthickness=0)
        self._win_id = self.canvas.create_window((0, 0), window=self.container, anchor="nw")

        def _on_config(_e=None):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            self.canvas.itemconfig(self._win_id, width=max(self.canvas.winfo_width(), 1))
        self.container.bind("<Configure>", _on_config)
        self.canvas.bind("<Configure>", _on_config)

        # 鼠标滚轮
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        # 右键菜单（canvas 空白区域时触发）
        self.canvas.bind("<Button-3>", self._on_canvas_right)

    def _on_wheel(self, evt):
        try:
            self.canvas.yview_scroll(int(-1 * (evt.delta / 120)), "units")
        except Exception:
            pass

    def _on_canvas_right(self, evt):
        # 点击空白时把第一个选中或最近点击的当作上下文
        if self.selected is not None and hasattr(self.selected, "_on_row_right"):
            # 用屏幕坐标弹出
            if callable(self.cb.get("on_context")):
                self.cb["on_context"](self.selected, evt)

    # ---------- 对外 API ----------
    def set_avds(self, avds_with_status):
        """avds_with_status: [(name, path, status)]  status ∈ {booted, booting, stopped}"""
        for r in self.rows:
            r.destroy()
        self.rows = []
        self.selected = None
        if self._empty is not None:
            try:
                self._empty.destroy()
            except Exception:
                pass
            self._empty = None

        if not avds_with_status:
            self._empty = tk.Label(self.container,
                                   text="（未发现 AVD，请点击下方「添加 AVD」）",
                                   bg=CARD, fg=MUTED, font=CN, anchor="w",
                                   padx=16, pady=18)
            self._empty.pack(fill="x")
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            return

        for idx, (name, path, st) in enumerate(avds_with_status):
            row = AvdRow(self.container, name, path, st, app_ref=self.app,
                         on_select=self._handle_select,
                         on_context=self.cb.get("on_context"),
                         row_index=idx)
            row.pack(fill="x", pady=1)
            self.rows.append(row)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def update_status_for(self, name, new_status):
        for r in self.rows:
            if r.avd_name == name:
                r.update_status(new_status)
                break

    def get_selected_name(self):
        return self.selected.avd_name if self.selected else None

    def expand_for(self, name, expand=True):
        for r in self.rows:
            if r.avd_name == name:
                r.toggle(expand=expand)
                break

    def _handle_select(self, row):
        if self.selected and self.selected is not row:
            self.selected.clear_selection_style()
        self.selected = row
        if callable(self.cb.get("on_select")):
            self.cb["on_select"](row.avd_name)


# ============================================================
# 启动自检对话框：检测并下载缺失的 SDK 组件
# ============================================================
class StartupCheckDialog(tk.Toplevel):
    """启动自检对话框：扫描必需 SDK 组件，缺失时提供下载。

    组件分两类：
      • cmdline-tools（sdkmanager + avdmanager）：无法自动下载，需手动安装
      • emulator / platform-tools：可由 sdkmanager 自动下载
    """
    # 可自动下载的组件：(key, 显示名, 检测路径, sdkmanager 包名)
    DOWNLOADABLE = [
        ("emulator", "模拟器主程序 (emulator/emulator.exe)", EMULATOR, "emulator"),
        ("platform-tools", "平台工具 (platform-tools/adb.exe)", ADB, "platform-tools"),
    ]
    CMDLINE_BIN = os.path.join(SDK_HOME, "cmdline-tools", "latest", "bin")
    # 各组件官方下载链接（用于点击后用默认浏览器打开）
    DOWNLOAD_LINKS = {
        "cmdline-tools": "https://developer.android.com/studio#command-line-tools-only",
        "emulator": "https://developer.android.com/studio",
        "platform-tools": "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
    }

    def __init__(self, master, app_ref):
        super().__init__(master)
        self.title("启动自检")
        self.configure(bg=BG)
        self.transient(master)
        self.app = app_ref
        self.checks = {}          # {key: BooleanVar}
        self._downloading = False
        self.dl_btn = None

        f = tk.Frame(self, bg=BG, padx=24, pady=20)
        f.pack(fill="both", expand=True)

        tk.Label(f, text="🔧 启动自检", bg=BG, fg=TEXT, font=CN_TITLE).pack(anchor="w", pady=(0, 6))

        cmdline_ok = os.path.exists(SDKMANAGER) and os.path.exists(AVDMANAGER)
        missing_dl = [(k, l, p, pkg) for k, l, p, pkg in self.DOWNLOADABLE
                      if not os.path.exists(p)]

        self._build_status(f, cmdline_ok, missing_dl)

        # 日志区
        tk.Label(f, text="安装日志", bg=BG, fg=MUTED, font=CN_SM, anchor="w").pack(fill="x", pady=(8, 2))
        self.log_box = tk.Text(f, font=CN_MONO, height=9, bg=LOG_BG, fg=LOG_FG, bd=0,
                               highlightthickness=1, highlightbackground=BORDER,
                               relief="flat", padx=6, pady=4)
        self.log_box.pack(fill="both", expand=True, pady=(0, 10))

        # 按钮区
        bf = tk.Frame(f, bg=BG)
        bf.pack(fill="x")
        make_button(bf, "关闭", self.destroy, "ghost").pack(side="right")
        if missing_dl and cmdline_ok:
            self.dl_btn = make_button(bf, "⬇ 下载并安装", self._start_download, "primary")
            self.dl_btn.pack(side="right", padx=(0, 8))
        elif not missing_dl and cmdline_ok:
            # 全部就绪，自动关闭
            self.after(1500, self.destroy)

        self.geometry("600x560")
        self.update_idletasks()
        # 居中于父窗口
        try:
            x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
            y = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 2
            self.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

    def _build_status(self, parent, cmdline_ok, missing_dl):
        if not cmdline_ok:
            tk.Label(parent, text="⚠ 核心工具 cmdline-tools 缺失，无法自动下载。",
                     bg=BG, fg=WARN, font=CN_BOLD, wraplength=540, justify="left").pack(anchor="w", pady=(0, 8))
            tk.Label(parent, text="请手动下载 cmdline-tools 并解压到：",
                     bg=BG, fg=TEXT_SOFT, font=CN_SM, anchor="w").pack(anchor="w")
            tk.Label(parent, text=self.CMDLINE_BIN, bg=BG, fg=TEXT, font=CN_MONO,
                     anchor="w", wraplength=540).pack(anchor="w", pady=(0, 8))
            # 可点击的下载链接
            link_row = tk.Frame(parent, bg=BG)
            link_row.pack(anchor="w", pady=(0, 8))
            tk.Label(link_row, text="下载地址：", bg=BG, fg=TEXT_SOFT, font=CN_SM).pack(side="left")
            make_link(link_row, "commandlinetools 官方下载页 ↗",
                      self.DOWNLOAD_LINKS["cmdline-tools"], font=CN_SM).pack(side="left")
            tk.Label(parent, text="解压后应包含：", bg=BG, fg=TEXT_SOFT, font=CN_SM,
                     anchor="w").pack(anchor="w")
            tk.Label(parent, text=os.path.join(self.CMDLINE_BIN, "sdkmanager.bat"),
                     bg=BG, fg=TEXT, font=CN_MONO, anchor="w").pack(anchor="w")
            tk.Label(parent, text=os.path.join(self.CMDLINE_BIN, "avdmanager.bat"),
                     bg=BG, fg=TEXT, font=CN_MONO, anchor="w").pack(anchor="w")
            # 同时缺失的 emulator / platform-tools 也给出直链
            if missing_dl:
                tk.Label(parent, text="", bg=BG).pack()
                tk.Label(parent, text="同时缺失以下组件，可手动下载：",
                         bg=BG, fg=TEXT_SOFT, font=CN_SM, anchor="w").pack(anchor="w", pady=(0, 4))
                for key, label, _p, _pkg in missing_dl:
                    row = tk.Frame(parent, bg=BG)
                    row.pack(fill="x", pady=1)
                    tk.Label(row, text=f"• {label}", bg=BG, fg=TEXT_SOFT, font=CN_SM).pack(side="left")
                    url = self.DOWNLOAD_LINKS.get(key, "")
                    if url:
                        make_link(row, "官方下载 ↗", url, font=CN_SM).pack(side="left", padx=(8, 0))
            tk.Label(parent, text="\n完成安装后重新启动本程序，自检将自动补齐其余组件。",
                     bg=BG, fg=TEXT_SOFT, font=CN_SM, wraplength=540, justify="left").pack(anchor="w", pady=(6, 0))
            return
        if not missing_dl:
            tk.Label(parent, text="✓ 所有必需组件均已就绪，无需下载。",
                     bg=BG, fg=SUCCESS, font=CN_BOLD).pack(anchor="w", pady=10)
            return
        tk.Label(parent, text="检测到以下组件缺失，已默认勾选（可点击右侧链接手动下载）：",
                 bg=BG, fg=TEXT, font=CN, wraplength=540, justify="left").pack(anchor="w", pady=(0, 10))
        checks_frame = tk.Frame(parent, bg=BG)
        checks_frame.pack(fill="x", pady=(0, 6))
        for key, label, _path, _pkg in missing_dl:
            row = tk.Frame(checks_frame, bg=BG)
            row.pack(fill="x", pady=2)
            var = tk.BooleanVar(value=True)
            self.checks[key] = var
            cb = tk.Checkbutton(row, text=label, variable=var,
                                bg=BG, fg=TEXT, selectcolor=CARD,
                                activebackground=BG, activeforeground=TEXT,
                                font=CN, anchor="w", bd=0,
                                highlightthickness=0)
            cb.pack(side="left")
            url = self.DOWNLOAD_LINKS.get(key, "")
            if url:
                make_link(row, "官方下载 ↗", url, font=CN_SM).pack(side="left", padx=(8, 0))

    def dlog(self, msg):
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")

    def _start_download(self):
        if self._downloading:
            return
        pkgs = []
        for key, _label, _path, pkg in self.DOWNLOADABLE:
            var = self.checks.get(key)
            if var and var.get():
                pkgs.append((key, pkg))
        if not pkgs:
            return
        self._downloading = True
        self.dl_btn.config(state="disabled", text="下载中…")
        pkg_ids = [pkg for _k, pkg in pkgs]

        def log_cb(line):
            self.after(0, lambda x=line: self.dlog(x))

        def worker():
            results = run_sdkmanager_install(pkg_ids, log_cb)
            self.after(0, lambda: self._on_done(results))

        threading.Thread(target=worker, daemon=True).start()

    def _on_done(self, results):
        self._downloading = False
        if self.dl_btn is not None:
            self.dl_btn.config(state="normal", text="⬇ 重新下载")
        # 重新扫描
        still_missing = [(k, l, p, pkg) for k, l, p, pkg in self.DOWNLOADABLE
                         if not os.path.exists(p)]
        if not still_missing:
            self.dlog("✓ 全部组件就绪！")
            if self.app is not None:
                try:
                    self.app.log("✓ 启动自检完成，所有必需组件已就绪。")
                except Exception:
                    pass
            if self.dl_btn is not None:
                self.dl_btn.config(state="disabled")
            self.after(1200, self.destroy)
        else:
            names = "、".join(l for _k, l, _p, _pkg in still_missing)
            self.dlog(f"⚠ 仍有 {len(still_missing)} 项未安装：{names}")
            if self.app is not None:
                try:
                    self.app.log(f"⚠ 启动自检：仍有缺失组件（{names}）。")
                except Exception:
                    pass


class LauncherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Android 模拟器启动器")
        self.geometry("860x680")
        self.minsize(800, 640)
        self.configure(bg=BG)
        # 设置窗口图标
        _ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")
        if os.path.isfile(_ico):
            try:
                self.iconbitmap(_ico)
            except Exception:
                pass
        self._last_devs = None
        self._last_boot = None
        self._avd_status = {}      # {avd_name: "booted"/"booting"}
        self._avd_serials = {}     # {avd_name: serial}
        self._setup_style()

        self._build_ui()
        # 启动时最大化窗口
        try:
            self.state("zoomed")
        except Exception:
            pass
        # 输出自动检测到的 SDK 路径
        self.log(f"📁 SDK 路径：{SDK_HOME}")
        self.after(120, self.refresh_avds)
        self.after(300, self._poll_status)
        # 启动自检：检测并下载缺失组件
        self.after(500, self._run_startup_selfcheck)

    def _run_startup_selfcheck(self):
        """启动自检：扫描必需组件，缺失时弹出对话框提供下载"""
        missing = []
        if not (os.path.exists(SDKMANAGER) and os.path.exists(AVDMANAGER)):
            missing.append("cmdline-tools")
        if not os.path.exists(EMULATOR):
            missing.append("emulator")
        if not os.path.exists(ADB):
            missing.append("platform-tools")
        if missing:
            self.log(f"🔧 启动自检：检测到缺失组件 {len(missing)} 项（{', '.join(missing)}），正在打开修复对话框…")
            try:
                StartupCheckDialog(self, self)
            except Exception as e:
                self.log(f"[错误] 自检对话框打开失败：{e}")
        else:
            self.log("✓ 启动自检通过，所有必需组件已就绪。")

    def _setup_style(self):
        try:
            st = ttk.Style()
            st.theme_use("clam")
            st.configure("TFrame", background=BG)
            st.configure("TLabel", background=BG, foreground=TEXT, font=CN)
            st.configure("Muted.TLabel", background=BG, foreground=MUTED, font=CN_SM)
            st.configure("TCombobox", fieldbackground=CARD, background=CARD,
                         foreground=TEXT, font=CN, arrowcolor=TEXT_SOFT,
                         bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
            st.map("TCombobox", fieldbackground=[("readonly", CARD)],
                   foreground=[("readonly", TEXT)],
                   arrowcolor=[("active", PRIMARY)])
            st.configure("TScrollbar", background=CARD, troughcolor=BG,
                         bordercolor=BG, arrowcolor=TEXT_SOFT,
                         lightcolor=CARD, darkcolor=CARD)
            st.map("TScrollbar", background=[("active", "#3C4043")])
        except Exception:
            pass

    def _build_ui(self):
        # ========== 顶栏（Material 深色表面 + 亮字）==========
        header = tk.Frame(self, bg=HEADER_BG, height=64)
        header.pack(fill="x")
        header.pack_propagate(False)
        # 左侧品牌区：标题 + 副标题
        brand = tk.Frame(header, bg=HEADER_BG)
        brand.pack(side="left", padx=24, pady=12)
        tk.Label(brand, text="Android 模拟器启动器", bg=HEADER_BG, fg=TEXT,
                 font=("Microsoft YaHei UI", 15, "bold"), anchor="w").pack(anchor="w")
        tk.Label(brand, text="Android Studio · 官方 AVD 管理（基于 avdmanager）", bg=HEADER_BG,
                 fg=TEXT_SOFT,
                 font=CN_SM, anchor="w").pack(anchor="w", pady=(2, 0))
        # 右侧状态（标题栏右上更精炼）
        tk.Label(header, text="🤖 Android SDK", bg=HEADER_BG, fg=PRIMARY,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(side="right", padx=24)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=24, pady=20)

        # ========== 顶部信息条（Chip 风格容器）==========
        top_row = tk.Frame(body, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        top_row.pack(fill="x", pady=(0, 16))
        top_inner = tk.Frame(top_row, bg=CARD)
        top_inner.pack(fill="x", padx=16, pady=10)

        # SDK 标签（Chip）：路径用 StringVar 绑定，跟随检测结果变化
        self.sdk_path_var = tk.StringVar(value=SDK_HOME)
        sdk_chip = tk.Frame(top_inner, bg=PRIMARY_SOFT, highlightthickness=1,
                            highlightbackground=PRIMARY)
        sdk_chip.pack(side="left")
        tk.Label(sdk_chip, text="📁 SDK", bg=PRIMARY_SOFT, fg=PRIMARY,
                 font=CN_SM, pady=5).pack(side="left", padx=(10, 4))
        tk.Label(sdk_chip, textvariable=self.sdk_path_var, bg=PRIMARY_SOFT, fg=PRIMARY,
                 font=CN_SM, pady=5).pack(side="left", padx=(0, 10))
        # 保留 AVD 路径变量（设置功能仍可用，但从 UI 删除入口，通过菜单访问）
        self.avd_path_var = tk.StringVar(value=AVD_USER_HOME)

        # 状态点（右上）
        state_box = tk.Frame(top_inner, bg=CARD)
        state_box.pack(side="right")
        self.status_label = tk.Label(state_box, text="检测中…", bg=CARD, fg=TEXT_SOFT,
                                     font=CN_BOLD)
        self.status_label.pack(side="left", padx=(0, 6))
        self.status_dot = tk.Label(state_box, text="●", bg=CARD, fg=MUTED,
                                   font=("Microsoft YaHei UI", 12, "bold"))
        self.status_dot.pack(side="left")

        # ========== 主水平分区分隔条（可拖动调整）：AVD 列表 | 模拟器窗口 ==========
        mid_pane = tk.PanedWindow(body, orient="horizontal", bg=BG,
                                  sashwidth=6, sashpad=0, sashrelief="flat",
                                  borderwidth=0)
        mid_pane.pack(fill="both", expand=True, pady=(0, 14))

        # 左：AVD 列表（已扩展，占原"运行状态"区域）
        left_card = make_card(mid_pane, padx=20, pady=18)
        left = pack_card(left_card)
        head_row = tk.Frame(left, bg=CARD)
        head_row.pack(fill="x", pady=(0, 10))
        tk.Label(head_row, text="可用虚拟设备 (AVD)", bg=CARD, fg=TEXT,
                 font=("Microsoft YaHei UI", 12, "bold"), anchor="w").pack(side="left")
        # 图例（Chip 风格）
        legend = tk.Frame(head_row, bg=CARD)
        legend.pack(side="right")
        for dot, txt, c in [("⚪", "未运行", MUTED), ("🟡", "开机中", WARN), ("🟢", "已开机", SUCCESS)]:
            chip = tk.Frame(legend, bg=CHIP_GRAY, highlightthickness=0)
            chip.pack(side="left", padx=(0, 6))
            tk.Label(chip, text=f"{dot}  {txt}", bg=CHIP_GRAY, fg=c,
                     font=CN_SM, padx=8, pady=3).pack()
        # AVD 可展开列表（每行点击展开显示状态/root/快捷按钮）
        self.avd_explist = AvdExpandableList(left, app_ref=self, callbacks={
            "on_select": lambda name: None,  # 选中时 self.selected_avd() 会直接从组件取值
            "on_context": self._show_avd_menu,
        })
        self.avd_explist.pack(fill="both", expand=True, pady=(4, 8))
        # 右键菜单（Material 风格，挂在 list canvas 上以防空白处点击）
        self.avd_menu = tk.Menu(self.avd_explist.canvas, tearoff=0, bg=CARD, fg=TEXT,
                                activebackground=PRIMARY_SOFT, activeforeground=PRIMARY,
                                relief="flat", bd=0, font=CN)
        # 添加 AVD 按钮行（左对齐、均等间距、Canvas 圆角 Material）
        add_row = tk.Frame(left, bg=CARD)
        add_row.pack(fill="x", pady=(4, 0))
        make_button(add_row, "＋ 添加 AVD", lambda: self.open_add_avd_dialog("pixel"),
                    "primary", padx=16, pady=7).pack(side="left")
        make_button(add_row, "导入 OTA 包", lambda: self.open_add_avd_dialog("ota"),
                    "ghost", padx=16, pady=7).pack(side="left", padx=8)
        make_button(add_row, "导入自定义镜像", lambda: self.open_add_avd_dialog("custom"),
                    "ghost", padx=16, pady=7).pack(side="left", padx=8)
        # 虚拟按键面板入口
        make_button(add_row, "🎛 虚拟按键", self.open_keypad,
                    "ghost", padx=16, pady=7).pack(side="right")
        mid_pane.add(left_card, minsize=800)

        # 日志（与上方分区可垂直拖动调整）
        bottom_pane = tk.PanedWindow(body, orient="vertical", bg=BG,
                                     sashwidth=6, sashrelief="raised",
                                     borderwidth=0)
        bottom_pane.pack(fill="both", expand=False)
        log_card = make_card(bottom_pane)
        log_inner = pack_card(log_card)
        tk.Label(log_inner, text="📝 运行日志", bg=CARD, fg=TEXT, font=CN_BOLD,
                 anchor="w").pack(fill="x", pady=(0, 6))
        log_frame = tk.Frame(log_inner, bg=LOG_BG)
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_frame, font=CN_MONO, bd=0, highlightthickness=0,
                                bg=LOG_BG, fg=LOG_FG, wrap="word", relief="flat",
                                insertbackground=LOG_FG, padx=8, pady=6, height=8)
        lsb = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.config(yscrollcommand=lsb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        lsb.pack(side="right", fill="y")
        self.log_text.configure(state="disabled")
        bottom_pane.add(log_card, minsize=80, height=180)
        self.log("启动器已就绪。状态自动检测中…  💡 提示：右键 AVD 可弹出操作菜单。")

    # ---------- 通用 ----------
    def log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def set_status(self, text, color=MUTED):
        """更新顶部状态点与文字（已移除运行状态分区）"""
        self.status_dot.config(fg=color)
        self.status_label.config(text=text, fg=color)

    def selected_avd(self):
        # 临时强制：用于 *_for(name) 包装方法
        forced = getattr(self, "_forced_avd_name", None)
        if forced:
            return forced
        if hasattr(self, "avd_explist") and self.avd_explist is not None:
            return self.avd_explist.get_selected_name()
        return None

    def _pin_avd(self, name):
        self._forced_avd_name = name

    def _unpin_avd(self):
        self._forced_avd_name = None

    # ---------- *-for-name 包装：把操作指向指定 AVD 名（给可展开栏快捷按钮用） ----------
    def start_avd(self, name, mode="normal"):
        self._pin_avd(name)
        try:
            self._start_with_mode(mode)
        finally:
            self._unpin_avd()

    def kill_emulator_for(self, name):
        self._pin_avd(name)
        try:
            self.kill_emulator()
        finally:
            self._unpin_avd()

    def delete_avd_for(self, name):
        self._pin_avd(name)
        try:
            self.delete_avd()
        finally:
            self._unpin_avd()

    def backup_avd_for(self, name):
        self._pin_avd(name)
        try:
            self.backup_avd()
        finally:
            self._unpin_avd()

    def restore_avd_for(self, name):
        self._pin_avd(name)
        try:
            self.restore_avd()
        finally:
            self._unpin_avd()

    def snapshot_avd_for(self, name):
        self._pin_avd(name)
        try:
            self.open_snapshot_dialog()
        finally:
            self._unpin_avd()

    def internal_for(self, name):
        self._pin_avd(name)
        try:
            self.open_internal_file_browser()
        finally:
            self._unpin_avd()

    def open_folder_for(self, name):
        self._pin_avd(name)
        try:
            self.open_avd_folder()
        finally:
            self._unpin_avd()

    def root_avd_gui(self, name):
        """给展开栏用的 root 入口：优先用 Root(adb)"""
        self._pin_avd(name)
        try:
            self.root_adb()
        finally:
            self._unpin_avd()

    # ---------- AVD 路径自定义 ----------
    def change_avd_path(self):
        """让用户选择新的 AVD 安装路径，保存并应用"""
        global AVD_USER_HOME
        new_path = filedialog.askdirectory(
            title="选择 AVD 安装路径", initialdir=AVD_USER_HOME, parent=self)
        if not new_path:
            return
        new_path = os.path.abspath(new_path)
        # 应用：更新全局变量 + 环境变量 + 设置文件 + UI
        AVD_USER_HOME = new_path
        os.environ["ANDROID_AVD_HOME"] = new_path
        self.avd_path_var.set(new_path)
        # 持久化
        s = load_settings()
        s["avd_home"] = new_path
        save_settings(s)
        self.log(f"AVD 安装路径已更改为：{new_path}")
        self.log("提示：avdmanager 与 emulator 将使用此路径读取/创建 AVD。")
        self.log("✓ 已完成!")
        self.refresh_avds()

    def _show_avd_menu(self, first, evt=None):
        """AVD 列表右键菜单。

        两种调用签名：
         - AvdRow._on_row_right(row, evt)       → first=row,     evt=evt
         - AvdExpandableList.canvas 右键(evt)  → first=evt
        """
        name = None
        popup_x_root, popup_y_root = 0, 0
        if isinstance(first, AvdRow):
            # row 右键
            row = first
            e = evt
            name = row.avd_name
            # 强行选中
            if self.avd_explist.selected is not row:
                if self.avd_explist.selected:
                    self.avd_explist.selected.clear_selection_style()
                self.avd_explist.selected = row
                row._on_row_click(e)  # 应用选中样式
            popup_x_root = e.x_root
            popup_y_root = e.y_root
        else:
            e = first
            # explist canvas 空白区域：用已选中项
            name = self.selected_avd()
            popup_x_root = e.x_root
            popup_y_root = e.y_root

        menu = self.avd_menu
        menu.delete(0, "end")
        if not name or name.startswith("（"):
            menu.add_command(label="（请先选择一个 AVD）", state="disabled")
        else:
            menu.add_command(label="▶  正常启动", command=lambda: self._start_with_mode("normal"))
            menu.add_command(label="⚡ Fastboot 启动",
                             command=lambda: self._start_with_mode("fastboot"))
            menu.add_command(label="🛠 Recovery 启动",
                             command=lambda: self._start_with_mode("recovery"))
            menu.add_separator()
            menu.add_command(label="📸 快照管理", command=self.open_snapshot_dialog)
            menu.add_command(label="🎛 虚拟按键面板", command=self.open_keypad)
            menu.add_command(label="🔑 Root (adb)", command=self.root_adb)
            menu.add_command(label="🧩 Root (Magisk)", command=self.root_magisk)
            menu.add_separator()
            menu.add_command(label="📦 安装 APK", command=self.install_apk)
            menu.add_separator()
            menu.add_command(label="💾 备份 AVD", command=self.backup_avd)
            menu.add_command(label="♻  恢复 AVD", command=self.restore_avd)
            menu.add_separator()
            menu.add_command(label="📂 打开 AVD 目录", command=self.open_avd_folder)
            menu.add_command(label="📁 AVD 内部文件（运行时）", command=self.open_internal_file_browser)
            menu.add_command(label="⚙  打开配置文件 (.ini)", command=self.open_avd_config_file)
            menu.add_separator()
            menu.add_command(label="🛑 关闭模拟器", command=self.kill_emulator)
            menu.add_command(label="🗑  删除 AVD", command=self.delete_avd)
        menu.tk_popup(popup_x_root, popup_y_root)

    def _start_with_mode(self, mode):
        """通过右键菜单指定的模式启动（直接调用 _launch_avd）"""
        name = self.selected_avd()
        if not name:
            messagebox.showwarning("提示", "请先选择一个 AVD。", parent=self)
            return
        if mode == "normal":
            self._launch_avd(name, None)
        else:
            self._launch_avd(name, mode)

    def _avd_path_of(self, name):
        """返回选中 AVD 的 .avd 目录（或 None）"""
        for n, p in list_avds():
            if n == name:
                return p
        return None

    def open_avd_folder(self):
        """在资源管理器中打开 AVD 数据目录（双击 / 右键菜单）"""
        name = self.selected_avd()
        if not name:
            messagebox.showwarning("提示", "请先选择一个 AVD。", parent=self)
            return
        path = self._avd_path_of(name)
        if not path or not os.path.isdir(path):
            messagebox.showwarning("提示", f"AVD 目录不存在或未找到：\n{path}", parent=self)
            return
        self.log(f"📂 打开 AVD 目录：{path}")
        try:
            os.startfile(path)
            self.log("✓ 已完成!")
        except Exception as e:
            messagebox.showerror("打开失败", f"无法打开目录：\n{path}\n\n{e}", parent=self)

    def open_avd_config_file(self):
        """打开 AVD 的全局 .ini 配置文件（<name>.ini，位于 AVD_USER_HOME 下）"""
        name = self.selected_avd()
        if not name:
            messagebox.showwarning("提示", "请先选择一个 AVD。", parent=self)
            return
        ini_path = os.path.join(AVD_USER_HOME, f"{name}.ini")
        if not os.path.isfile(ini_path):
            messagebox.showwarning("提示", f"找不到配置文件：\n{ini_path}", parent=self)
            return
        self.log(f"⚙ 打开 AVD 配置文件：{ini_path}")
        try:
            os.startfile(ini_path)
        except Exception as e:
            messagebox.showerror("打开失败", f"无法打开配置文件：\n{ini_path}\n\n{e}", parent=self)

    def open_internal_file_browser(self):
        """打开 AVD 运行时内部文件浏览器（通过 adb 访问模拟器文件系统）。"""
        # 先找选中 AVD 对应的在线 serial
        name = self.selected_avd()
        serial = None
        if name:
            serial = self._avd_serials.get(name)
        if not serial:
            # 兜底：选第一个在线 emulator
            devs = running_devices()
            if devs:
                serial = devs[0][0]
                name = name or serial
            else:
                messagebox.showwarning("提示", "暂无运行中的模拟器。请先启动要浏览内部文件的 AVD。", parent=self)
                return
        dlg = InternalFileBrowser(self, serial, avd_name=name, log_fn=self.log)
        dlg.grab_release()  # 非模态，允许同时操作主窗口
        self.log("✓ 已完成!")

    # ---------- 虚拟按键面板 ----------
    def open_keypad(self):
        """打开悬浮于 AVD 窗口之上的虚拟按键面板（电源 / 音量 +/-）。"""
        # 尽量关联当前选中的 AVD（若已开机）
        name = self.selected_avd()
        serial = self._avd_serials.get(name) if name else None
        if not serial:
            devs = running_devices()
            if devs:
                serial = devs[0][0]
                rmap = {s: n for n, s in self._avd_serials.items()}
                name = rmap.get(serial)
        # 没开机也允许打开面板（顶部选目标），只是没有贴靠
        pad = AdbKeyPad(self, initial_serial=serial, initial_avd=name, log_fn=self.log)
        pad.grab_release()
        self.log("✓ 已完成!")
        self.log("🎛 已打开虚拟按键面板（置顶，可拖动，可选贴靠 AVD 窗口）。")

    # ---------- 自动状态轮询 ----------
    def _poll_status(self):
        """每 2 秒检查 adb 设备状态，变化时自动刷新 UI 与 AVD 列表前缀"""
        try:
            devs = running_devices()
            status_map, serial_map = running_avd_map()
            # 状态指纹：运行中的 AVD 名 + 状态
            fp_key = tuple(sorted((n, s) for n, s in status_map.items()))
            if fp_key != self._last_devs:
                self._last_devs = fp_key
                self._avd_status = status_map
                self._avd_serials = serial_map
                self._update_status_ui(status_map)
        except Exception:
            pass
        self.after(2000, self._poll_status)

    def _update_status_ui(self, status_map):
        """更新顶部状态点 + 重新渲染 AVD 列表（带状态前缀）"""
        if not status_map:
            self.set_status("当前无运行中的模拟器", MUTED)
        else:
            booted = sum(1 for s in status_map.values() if s == "booted")
            total = len(status_map)
            self.set_status(f"{total} 个模拟器运行中（{booted} 已开机）", SUCCESS)
        # 重新渲染列表（保留选中）
        self.refresh_avds()

    def refresh_avds(self):
        """重新加载 AVD 可展开列表；保留当前选中行与展开状态。"""
        selected_name = self.selected_avd()
        # 记展开状态
        expanded_names = set()
        if hasattr(self, "avd_explist") and self.avd_explist is not None:
            for r in getattr(self.avd_explist, "rows", []):
                if getattr(r, "_expanded", False):
                    expanded_names.add(r.avd_name)

        avds = list_avds()
        rows = []
        for name, path in avds:
            st = self._avd_status.get(name) or "stopped"
            rows.append((name, path, st))
        self.avd_explist.set_avds(rows)

        # 恢复选中 & 展开
        if selected_name:
            for r in self.avd_explist.rows:
                if r.avd_name == selected_name:
                    if self.avd_explist.selected and self.avd_explist.selected is not r:
                        self.avd_explist.selected.clear_selection_style()
                    self.avd_explist.selected = r
                    r._on_row_click(None)
                    break
        for r in self.avd_explist.rows:
            if r.avd_name in expanded_names:
                r.toggle(expand=True)

        if not getattr(self, "_avd_listed", False):
            self.log(f"已加载 {len(avds)} 个 AVD。")
            self._avd_listed = True

    # ---------- 启动模式选择 ----------
    def show_start_menu(self):
        name = self.selected_avd()
        if not name:
            messagebox.showwarning("提示", "请先在左侧选择一个 AVD。", parent=self)
            return
        if not os.path.exists(EMULATOR):
            messagebox.showerror("错误", f"找不到 emulator.exe：\n{EMULATOR}", parent=self)
            return
        StartModeDialog(self, name, self._launch_avd)

    def _launch_avd(self, name, mode):
        """mode: normal / fastboot / recovery"""
        self.log(f"启动模拟器：{name}（模式：{mode}）…")
        threading.Thread(target=run_stream,
                         args=([EMULATOR, "-avd", name, "-no-snapshot-load"], self.log),
                         daemon=True).start()
        self.log("✓ 已完成!")
        if mode in ("fastboot", "recovery"):
            reboot_target = "bootloader" if mode == "fastboot" else "recovery"
            self.log(f"等待设备上线后切换到 {mode} 模式…")
            threading.Thread(target=self._wait_and_reboot,
                             args=(reboot_target, self.log), daemon=True).start()

    def _wait_and_reboot(self, target, log):
        """等待设备上线，然后 adb reboot 到指定模式"""
        deadline = time.time() + 60
        while time.time() < deadline:
            devs = running_devices()
            for serial, state in devs:
                if state == "device" and boot_completed(serial) == "1":
                    log(f"设备 {serial} 已开机，执行 adb reboot {target} …")
                    run_stream([ADB, "-s", serial, "reboot", target], log)
                    return
            time.sleep(2)
        log("[超时] 等待设备上线超时，未能切换模式。")

    # ---------- 关闭 ----------
    def kill_emulator(self):
        devs = running_devices()
        if not devs:
            self.log("没有正在运行的模拟器可关闭。")
            return
        for serial, _state in devs:
            self.log(f"关闭 {serial} …")
            threading.Thread(target=run_stream,
                             args=([ADB, "-s", serial, "emu", "kill"], self.log),
                             daemon=True).start()
        self.log("✓ 已完成!")

    # ---------- 安装 APK ----------
    def install_apk(self):
        devs = [s for (s, st) in running_devices() if st == "device"]
        if not devs:
            messagebox.showwarning("提示", "没有正在运行的模拟器，请先启动。", parent=self)
            return
        path = filedialog.askopenfilename(
            title="选择 APK 文件",
            filetypes=[("APK 文件", "*.apk"), ("所有文件", "*.*")], parent=self)
        if not path:
            return
        target = devs[0]
        self.log(f"向 {target} 安装：{path}")
        threading.Thread(target=run_stream,
                         args=([ADB, "-s", target, "install", "-r", path], self.log),
                         daemon=True).start()
        self.log("✓ 已完成!")

    # ---------- 删除 AVD ----------
    def delete_avd(self):
        name = self.selected_avd()
        if not name:
            messagebox.showwarning("提示", "请先在左侧选择要删除的 AVD。", parent=self)
            return
        # 若该 AVD 正在运行，提示先关闭
        devs = running_devices()
        if devs:
            messagebox.showwarning("提示",
                "检测到有模拟器正在运行，删除前请先点击「关闭模拟器」。\n"
                "删除正在运行的 AVD 可能导致文件占用而失败。", parent=self)
            return
        if not messagebox.askyesno("确认删除",
                f"确定要删除 AVD「{name}」吗？\n\n"
                "该操作将移除 AVD 配置及其虚拟设备数据（不会删除系统镜像），且不可恢复。",
                parent=self):
            return
        if not os.path.exists(AVDMANAGER):
            messagebox.showerror("错误", f"找不到 avdmanager.bat：\n{AVDMANAGER}", parent=self)
            return
        self.log(f"删除 AVD：{name} …")

        def worker():
            proc = subprocess.Popen(
                [AVDMANAGER, "delete", "avd", "-n", name],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW)
            out, _ = proc.communicate(timeout=60)
            text = out.decode("utf-8", errors="replace")
            self.after(0, lambda: self._on_delete_done(proc.returncode, text, name))

        threading.Thread(target=worker, daemon=True).start()

    def _on_delete_done(self, code, text, name):
        for line in text.splitlines():
            self.log(f"  {line}")
        if code == 0:
            self.log(f"✓ AVD「{name}」已删除。")
            self.log("✓ 已完成!")
            self.refresh_avds()
        else:
            self.log(f"✗ 删除失败，退出码 {code}")

    # ---------- 备份 AVD ----------
    def backup_avd(self):
        name = self.selected_avd()
        if not name:
            messagebox.showwarning("提示", "请先在左侧选择要备份的 AVD。", parent=self)
            return
        # 运行中无法可靠备份（userdata 会被占用）
        devs = running_devices()
        if devs:
            messagebox.showwarning("提示",
                "检测到有模拟器正在运行，备份前请先点击「关闭模拟器」。\n"
                "运行中的 AVD 文件可能被占用，导致备份不完整。", parent=self)
            return
        # 定位 AVD 目录与 .ini
        avds = list_avds()
        avd_path = next((p for (n, p) in avds if n == name), None)
        if not avd_path or not os.path.isdir(avd_path):
            messagebox.showerror("错误", f"找不到 AVD 目录：\n{avd_path}", parent=self)
            return
        ini_file = os.path.join(os.path.dirname(avd_path), name + ".ini")
        if not os.path.exists(ini_file):
            messagebox.showerror("错误", f"找不到 AVD 配置文件：\n{ini_file}", parent=self)
            return

        # 选择备份保存位置
        default_name = f"{name}_backup_{time.strftime('%Y%m%d_%H%M%S')}.zip"
        zip_path = filedialog.asksaveasfilename(
            title="选择备份保存位置",
            defaultextension=".zip",
            initialfile=default_name,
            filetypes=[("ZIP 备份包", "*.zip"), ("所有文件", "*.*")],
            parent=self)
        if not zip_path:
            return

        self.log(f"开始备份 AVD「{name}」到 {zip_path} …")
        threading.Thread(target=self._backup_worker,
                         args=(name, avd_path, ini_file, zip_path),
                         daemon=True).start()

    def _backup_worker(self, name, avd_path, ini_file, zip_path):
        """后台打包 AVD 目录 + .ini 配置为 zip"""
        try:
            import zipfile
            total = 0
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                # 1. 写入 .ini 配置
                zf.write(ini_file, arcname=os.path.basename(ini_file))
                self.after(0, lambda: self.log(f"  + {os.path.basename(ini_file)}"))
                total += 1
                # 2. 递归写入 AVD 目录内容
                for root, _dirs, files in os.walk(avd_path):
                    for fn in files:
                        abs_p = os.path.join(root, fn)
                        # 相对于 AVD 根目录的相对路径
                        rel = os.path.relpath(abs_p, avd_path)
                        arc = os.path.join(os.path.basename(avd_path), rel)
                        zf.write(abs_p, arcname=arc)
                        total += 1
                        # 跳过大文件的逐条日志，避免刷屏
                        size = os.path.getsize(abs_p)
                        if size < 10 * 1024 * 1024:
                            self.after(0, lambda a=arc: self.log(f"  + {a}"))
                        else:
                            self.after(0, lambda a=arc, s=size: self.log(
                                f"  + {a}  ({s // (1024*1024)} MB)"))
            # 写入清单文件，记录 AVD 名称（恢复时用）
            with zipfile.ZipFile(zip_path, "a", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("__avd_backup__.json",
                            json.dumps({"avd_name": name, "avd_dir": os.path.basename(avd_path),
                                        "created": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False))
            self.after(0, lambda: self._backup_done(True, zip_path, total, ""))
        except Exception as e:
            self.after(0, lambda: self._backup_done(False, zip_path, total, str(e)))

    def _backup_done(self, ok, zip_path, count, err):
        if ok:
            size_mb = os.path.getsize(zip_path) / (1024 * 1024)
            self.log(f"✓ 备份完成：{zip_path}")
            self.log(f"  共 {count} 个文件，压缩后 {size_mb:.1f} MB")
            self.log("✓ 已完成!")
            messagebox.showinfo("备份完成",
                f"AVD 已备份到：\n{zip_path}\n\n共 {count} 个文件，压缩后 {size_mb:.1f} MB。",
                parent=self)
        else:
            self.log(f"✗ 备份失败：{err}")
            messagebox.showerror("备份失败", err, parent=self)

    # ---------- 恢复 AVD ----------
    def restore_avd(self):
        zip_path = filedialog.askopenfilename(
            title="选择 AVD 备份包",
            filetypes=[("ZIP 备份包", "*.zip"), ("所有文件", "*.*")], parent=self)
        if not zip_path:
            return
        # 读取备份清单，获取原始 AVD 名称
        try:
            import zipfile
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = zf.namelist()
                if "__avd_backup__.json" not in names:
                    messagebox.showerror("错误",
                        "该 zip 不是有效的 AVD 备份包（缺少 __avd_backup__.json 清单）。",
                        parent=self)
                    return
                manifest = json.loads(zf.read("__avd_backup__.json").decode("utf-8"))
                orig_name = manifest.get("avd_name", "RestoredAVD")
                orig_dir = manifest.get("avd_dir", orig_name + ".avd")
        except Exception as e:
            messagebox.showerror("错误", f"无法读取备份包：{e}", parent=self)
            return

        # 若同名 AVD 已存在，提示
        existing = [n for (n, _p) in list_avds()]
        if orig_name in existing:
            if not messagebox.askyesno("AVD 已存在",
                    f"名为「{orig_name}」的 AVD 已存在。\n是否覆盖？现有数据将被替换。",
                    parent=self):
                return

        self.log(f"开始从备份恢复 AVD「{orig_name}」…")
        self.log(f"备份文件：{zip_path}")
        threading.Thread(target=self._restore_worker,
                         args=(zip_path, orig_name, orig_dir),
                         daemon=True).start()

    def _restore_worker(self, zip_path, orig_name, orig_dir):
        """后台解压备份，恢复 AVD 目录与 .ini 配置"""
        try:
            import zipfile
            avd_home = AVD_USER_HOME
            os.makedirs(avd_home, exist_ok=True)
            avd_path = os.path.join(avd_home, orig_dir)

            with zipfile.ZipFile(zip_path, "r") as zf:
                for info in zf.infolist():
                    fn = info.filename
                    # 跳过清单文件
                    if fn == "__avd_backup__.json":
                        continue
                    # .ini 配置 -> 直接放到 avd_home
                    if fn.endswith(".ini") and "/" not in fn.replace("\\", "/"):
                        target = os.path.join(avd_home, fn)
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        with zf.open(info) as src, open(target, "wb") as dst:
                            dst.write(src.read())
                        self.after(0, lambda f=fn: self.log(f"  恢复配置 {f}"))
                        continue
                    # AVD 目录内容 -> 去掉 orig_dir 前缀，放到 avd_path 下
                    norm = fn.replace("\\", "/")
                    parts = norm.split("/", 1)
                    if len(parts) == 2 and parts[0] == orig_dir:
                        rel = parts[1]
                    else:
                        # 兜底：保留原始相对结构
                        rel = norm
                    target = os.path.join(avd_path, rel)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with zf.open(info) as src, open(target, "wb") as dst:
                        dst.write(src.read())
                    size = info.file_size
                    if size < 10 * 1024 * 1024:
                        self.after(0, lambda r=rel: self.log(f"  + {r}"))
                    else:
                        self.after(0, lambda r=rel, s=size: self.log(f"  + {r}  ({s // (1024*1024)} MB)"))
            self.after(0, lambda: self._restore_done(True, orig_name, ""))
        except Exception as e:
            self.after(0, lambda: self._restore_done(False, orig_name, str(e)))

    def _restore_done(self, ok, name, err):
        if ok:
            self.log(f"✓ AVD「{name}」已恢复。")
            self.log("✓ 已完成!")
            self.refresh_avds()
            messagebox.showinfo("恢复完成",
                f"AVD「{name}」已成功恢复。\n可在左侧列表中查看并启动。",
                parent=self)
        else:
            self.log(f"✗ 恢复失败：{err}")
            messagebox.showerror("恢复失败", err, parent=self)

    # ---------- 添加 AVD ----------
    def open_add_avd_dialog(self, mode):
        if mode == "pixel":
            PixelWizardDialog(self, on_created=self.refresh_avds)
        elif mode == "ota":
            OtaImportDialog(self, on_done=self.refresh_avds)
        elif mode == "custom":
            CustomImageImportDialog(self, on_created=self.refresh_avds)

    # ---------- 快照管理 ----------
    def open_snapshot_dialog(self):
        devs = [s for (s, st) in running_devices() if st == "device"]
        if not devs:
            messagebox.showwarning("提示", "快照操作需要模拟器正在运行，请先启动。", parent=self)
            return
        SnapshotDialog(self, devs[0])
        self.log("✓ 已完成!")

    # ---------- Root(adb) ----------
    def root_adb(self):
        devs = [s for (s, st) in running_devices() if st == "device"]
        if not devs:
            messagebox.showwarning("提示", "请先启动要 root 的模拟器。", parent=self)
            return
        target = devs[0]
        # 先检查是否已 root
        already, detail = adb_root_status(target)
        if already:
            self.log(f"[Root(adb)] {target} 已是 root 状态：{detail}")
            self.log("[Root(adb)] 无需操作，可直接用 adb shell 进入 root 提示符。")
            messagebox.showinfo("Root(adb)", f"设备已是 root 状态：\n{detail}", parent=self)
            return
        self.log(f"[Root(adb)] 对 {target} 执行 adb root …")

        def runner():
            try:
                result = subprocess.run(
                    [ADB, "-s", target, "root"],
                    capture_output=True, timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                out = (result.stdout + result.stderr).decode("utf-8", errors="replace").strip()
                if out:
                    for line in out.splitlines():
                        self.log(f"  {line}")
                # 等待 adbd 重启
                time.sleep(3)
                ok, detail = adb_root_status(target)
                if ok:
                    self.log(f"[Root(adb)] ✓ 成功！{detail}")
                    self.log("[Root(adb)] 现可用 adb shell 进入 root (#) 提示符。")
                    self.log("✓ 已完成!")
                else:
                    self.log(f"[Root(adb)] 验证失败：{detail}")
                    self.log("[Root(adb)] 该镜像可能不支持 adb root（请确认使用 google_apis 而非 playstore 镜像）。")
            except subprocess.TimeoutExpired:
                self.log("[Root(adb)] adb root 超时。")
            except Exception as e:
                self.log(f"[Root(adb)] 异常：{e}")

        threading.Thread(target=runner, daemon=True).start()

    # ---------- Root(Magisk) ----------
    def root_magisk(self):
        name = self.selected_avd()
        if not name:
            messagebox.showwarning("提示", "请先在左侧选择要 root 的 AVD。", parent=self)
            return
        if not os.path.exists(GIT_BASH):
            messagebox.showerror("错误",
                "未找到 Git Bash：\n" + GIT_BASH +
                "\n\nMagisk root 方案依赖 Git Bash 执行 rootAVD.sh。", parent=self)
            return
        devs = [s for (s, st) in running_devices() if st == "device"]
        if not devs:
            messagebox.showwarning("提示",
                "Magisk root 需要模拟器正在运行。\n请先启动并等待开机完成。", parent=self)
            return
        if not messagebox.askyesno("确认 Magisk Root",
                f"将对 AVD「{name}」执行 Magisk root（修补 ramdisk）。\n继续？", parent=self):
            return
        MagiskRootJob(self, name)
        self.log("✓ 已完成!")


# ============================================================
# 启动模式选择对话框
# ============================================================
class StartModeDialog(tk.Toplevel):
    def __init__(self, master, avd_name, on_launch):
        super().__init__(master)
        self.title("选择启动模式")
        self.configure(bg=BG)
        self.transient(master)
        self.grab_set()
        self.avd_name = avd_name
        self.on_launch = on_launch

        f = tk.Frame(self, bg=BG, padx=24, pady=20)
        f.pack(fill="both", expand=True)
        tk.Label(f, text=f"启动 AVD：{avd_name}", bg=BG, fg=TEXT,
                 font=CN_BOLD).pack(pady=(0, 16))
        tk.Label(f, text="请选择启动模式：", bg=BG, fg=MUTED, font=CN).pack(anchor="w", pady=(0, 8))

        modes = [
            ("正常启动", "正常进入 Android 系统", "normal", SUCCESS),
            ("Fastboot 模式", "启动后进入 bootloader（fastboot）", "fastboot", ACCENT),
            ("Recovery 模式", "启动后进入恢复模式", "recovery", WARN),
        ]
        for label, desc, mode, color in modes:
            row = tk.Frame(f, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
            row.pack(fill="x", pady=4)
            inner = tk.Frame(row, bg=CARD)
            inner.pack(fill="x", padx=12, pady=10)
            tk.Label(inner, text=label, bg=CARD, fg=TEXT, font=CN_BOLD).pack(side="left")
            tk.Label(inner, text=desc, bg=CARD, fg=MUTED, font=CN_SM).pack(side="left", padx=12)
            make_button(inner, "启动", lambda m=mode: self._choose(m), "primary").pack(side="right")

        make_button(f, "取消", self.destroy, "ghost").pack(pady=(16, 0))
        self.geometry("460x320")
        self.update_idletasks()
        x = master.winfo_rootx() + 100
        y = master.winfo_rooty() + 80
        self.geometry(f"+{x}+{y}")

    def _choose(self, mode):
        self.on_launch(self.avd_name, mode)
        self.destroy()


# ============================================================
# 添加 AVD - Pixel 机型向导
# ============================================================
class PixelWizardDialog(tk.Toplevel):
    def __init__(self, master, on_created):
        super().__init__(master)
        self.title("添加 AVD - Pixel 机型向导")
        self.configure(bg=BG)
        self.transient(master)
        self.grab_set()
        self.on_created = on_created
        self.pixels = list_pixel_devices()
        self.installed_apis = list_installed_images()
        # 在线检查扩展：额外发现的 API -> pkg_id / 版本标签
        self.online_apis = set()
        self.online_pkgs = {}
        self.extra_labels = {}
        self.selected_device = None
        self.selected_api = None
        self.ver_radio_var = tk.StringVar(value="")
        self._download_threads = set()
        self._checking_online = False

        f = tk.Frame(self, bg=BG, padx=18, pady=16)
        f.pack(fill="both", expand=True)
        title_row = tk.Frame(f, bg=BG)
        title_row.pack(fill="x", pady=(0, 2))
        tk.Label(title_row, text="Pixel 机型向导", bg=BG, fg=TEXT, font=CN_BOLD).pack(side="left")
        self.online_status = tk.Label(title_row, text="🔄 正在检查最新 Pixel 机型与 Android 版本…",
                                       bg=BG, fg=ACCENT, font=CN_SM)
        self.online_status.pack(side="right")
        tk.Label(f, text="选择 Pixel 机型 → 选择 Android 版本 → 下载镜像（未安装时）→ 创建 AVD",
                 bg=BG, fg=MUTED, font=CN_SM).pack(anchor="w", pady=(0, 12))

        cols = tk.Frame(f, bg=BG)
        cols.pack(fill="both", expand=True)

        # 左：Pixel 机型列表
        left_card = make_card(cols)
        left_card.pack(side="left", fill="both", expand=True, padx=(0, 8))
        left = pack_card(left_card)
        tk.Label(left, text="1. 选择 Pixel 机型", bg=CARD, fg=TEXT, font=CN_BOLD).pack(anchor="w", pady=(0, 6))
        lsf = tk.Frame(left, bg=CARD)
        lsf.pack(fill="both", expand=True)
        lsb = ttk.Scrollbar(lsf)
        lsb.pack(side="right", fill="y")
        self.dev_listbox = tk.Listbox(lsf, font=CN, bd=0, highlightthickness=0,
                                      selectbackground=ACCENT_SOFT, selectforeground=ACCENT,
                                      activestyle="none", bg=CARD, fg=TEXT, height=12)
        self.dev_listbox.pack(side="left", fill="both", expand=True)
        self.dev_listbox.config(yscrollcommand=lsb.set)
        lsb.config(command=self.dev_listbox.yview)
        for dev_id, dev_name in self.pixels:
            self.dev_listbox.insert("end", dev_name)
        self.dev_listbox.bind("<<ListboxSelect>>", self._on_device_select)

        # 右：Android 版本列表（含下载状态）
        right_card = make_card(cols)
        right_card.pack(side="right", fill="both", expand=True)
        right = pack_card(right_card)
        tk.Label(right, text="2. 选择 Android 版本", bg=CARD, fg=TEXT, font=CN_BOLD).pack(anchor="w", pady=(0, 6))
        self.version_label = tk.Label(right, text="← 请先选择左侧机型", bg=CARD, fg=MUTED, font=CN_SM)
        self.version_label.pack(anchor="w", pady=(0, 6))
        vsf = tk.Frame(right, bg=CARD)
        vsf.pack(fill="both", expand=True)
        # 纵向滚动条
        vsb_y = ttk.Scrollbar(vsf, orient="vertical")
        vsb_y.pack(side="right", fill="y")
        # 横向滚动条（版本卡片多时可用）
        vsb_x = ttk.Scrollbar(vsf, orient="horizontal")
        vsb_x.pack(side="bottom", fill="x")
        self.ver_canvas = tk.Canvas(vsf, bg=CARD, highlightthickness=0, bd=0)
        self.ver_inner = tk.Frame(self.ver_canvas, bg=CARD)
        self.ver_canvas_window = self.ver_canvas.create_window(
            (0, 0), window=self.ver_inner, anchor="nw")
        self.ver_canvas.pack(side="left", fill="both", expand=True)
        vsb_y.config(command=self.ver_canvas.yview)
        vsb_x.config(command=self.ver_canvas.xview)
        self.ver_canvas.config(yscrollcommand=vsb_y.set, xscrollcommand=vsb_x.set)

        def _on_inner_config(_evt):
            self.ver_canvas.configure(scrollregion=self.ver_canvas.bbox("all"))
        self.ver_inner.bind("<Configure>", _on_inner_config)

        def _on_canvas_config(evt):
            self.ver_canvas.itemconfig(self.ver_canvas_window, width=evt.width)
            self.ver_canvas.configure(scrollregion=self.ver_canvas.bbox("all"))
            # 窗口 resize 时重排卡片 grid
            self._relayout_version_cards()
        self.ver_canvas.bind("<Configure>", _on_canvas_config)

        def _on_mousewheel(evt):
            self.ver_canvas.yview_scroll(int(-1 * (evt.delta / 120)), "units")
        self.ver_canvas.bind("<MouseWheel>", _on_mousewheel)
        self.ver_inner.bind("<MouseWheel>", _on_mousewheel)

        # AVD 名称
        name_row = tk.Frame(f, bg=BG)
        name_row.pack(fill="x", pady=(12, 0))
        tk.Label(name_row, text="AVD 名称：", bg=BG, fg=TEXT, font=CN).pack(side="left")
        self.name_var = tk.StringVar()
        tk.Entry(name_row, textvariable=self.name_var, font=CN, width=24, bg=CARD, fg=TEXT,
                 relief="flat", bd=0, highlightthickness=1,
                 highlightbackground=BORDER).pack(side="left", padx=6, ipady=3)

        # AVD 存储位置（每台 AVD 可单独指定）
        loc_row = tk.Frame(f, bg=BG)
        loc_row.pack(fill="x", pady=(8, 0))
        tk.Label(loc_row, text="存储位置：", bg=BG, fg=TEXT, font=CN).pack(side="left")
        self.loc_var = tk.StringVar(value=AVD_USER_HOME)
        tk.Entry(loc_row, textvariable=self.loc_var, font=CN, width=38, bg=CARD, fg=TEXT,
                 relief="flat", bd=0, highlightthickness=1,
                 highlightbackground=BORDER).pack(side="left", padx=6, ipady=3)
        make_button(loc_row, "📂 浏览…", self._browse_loc, "ghost").pack(side="left", padx=(4, 0))
        tk.Label(loc_row, text="留空则用默认 AVD 目录", bg=BG, fg=MUTED, font=CN_SM).pack(side="left", padx=(6, 0))

        # 日志
        self.log_box = tk.Text(f, font=CN_MONO, height=5, bg=LOG_BG, fg=LOG_FG, bd=0,
                               highlightthickness=1, highlightbackground=BORDER,
                               relief="flat", padx=6, pady=4)
        self.log_box.pack(fill="x", pady=(10, 8))

        # 按钮
        bf = tk.Frame(f, bg=BG)
        bf.pack(fill="x")
        make_button(bf, "取消", self.destroy, "ghost").pack(side="right")
        self.create_btn = make_button(bf, "创建 AVD", self.do_create, "primary")
        self.create_btn.pack(side="right", padx=(0, 8))

        self.geometry("780x580")

        # 启动在线检查线程（后台刷新机型 & Android 版本）
        threading.Thread(target=self._check_online_updates, daemon=True).start()

    def dlog(self, msg):
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")

    def _label_for_api(self, api):
        if api in ANDROID_VERSIONS:
            return ANDROID_VERSIONS[api]
        if api in self.extra_labels:
            return self.extra_labels[api]
        # 未知 API，兜底显示（数字）
        return f"Android (API {api})"

    def _api_is_available_online(self, api):
        return api in self.installed_apis or api in self.online_apis

    def _check_online_updates(self):
        """后台线程：调用 sdkmanager --list 检查最新 system-images 与 Pixel 机型。"""
        self._checking_online = True
        try:
            self.after(0, lambda: self.online_status.config(
                text="🔄 正在连接 Google SDK 仓库…", fg=WARN))
            # 1) 检查可用 system-images
            apis, pkgs = list_available_system_images_online(timeout=90)
            new_online_apis = set(apis) - self.installed_apis
            self.online_apis = set(apis)
            self.online_pkgs = pkgs
            # 2) 重新 list_pixel_devices（avdmanager 会从最新 SDK 数据拉取设备，可能发现新机型）
            refreshed = list_pixel_devices()
            updated_labels = refresh_android_version_labels(new_online_apis)
            self.extra_labels = updated_labels
            # 3) 对比变化，刷新 UI
            old_ids = set(d[0] for d in self.pixels)
            new_ids = set(d[0] for d in refreshed)
            added_ids = new_ids - old_ids
            if new_online_apis or added_ids:
                self.pixels = refreshed
                self.installed_apis = list_installed_images()
                # 切回主线程刷新
                self.after(0, self._refresh_after_online_check)
                detail_parts = []
                if new_online_apis:
                    labels = []
                    for a in sorted(new_online_apis):
                        labels.append(self._label_for_api(a) + f" (API {a})")
                    detail_parts.append("新 Android 版本：" + "、".join(labels))
                if added_ids:
                    labels = []
                    for d_id, d_name in refreshed:
                        if d_id in added_ids:
                            labels.append(d_name)
                    detail_parts.append("新机型：" + "、".join(labels))
                self.after(0, lambda: self.online_status.config(
                    text="✅ 已检查更新｜" + "｜".join(detail_parts), fg=SUCCESS))
            else:
                self.installed_apis = list_installed_images()
                self.after(0, lambda: self.online_status.config(
                    text="✅ 已是最新版本（当前最新 Pixel & Android 已收录）", fg=SUCCESS))
        except Exception as e:
            self.after(0, lambda: self.online_status.config(
                text=f"⚠ 在线检查失败：{e}", fg=DANGER))
        finally:
            self._checking_online = False

    def _refresh_after_online_check(self):
        # 刷新 Pixel 机型列表（保留选中）
        cur = self.dev_listbox.curselection()
        cur_idx = cur[0] if cur else None
        cur_id = None
        if cur_idx is not None and cur_idx < len(self.pixels):
            cur_id = self.pixels[cur_idx][0]
        self.dev_listbox.delete(0, "end")
        for _dev_id, dev_name in self.pixels:
            self.dev_listbox.insert("end", dev_name)
        # 恢复选中
        if cur_id:
            for i, (d_id, _n) in enumerate(self.pixels):
                if d_id == cur_id:
                    self.dev_listbox.selection_clear(0, "end")
                    self.dev_listbox.selection_set(i)
                    self.dev_listbox.activate(i)
                    break
        # 如果有选中机型，重新生成右侧版本列表
        sel = self.dev_listbox.curselection()
        if sel:
            self._on_device_select(None, _skip_sel_check=True)

    def _browse_loc(self):
        p = filedialog.askdirectory(title="选择 AVD 存储位置",
                                     initialdir=self.loc_var.get() or AVD_USER_HOME,
                                     parent=self)
        if p:
            self.loc_var.set(p)

    def _on_device_select(self, _evt, _skip_sel_check=False):
        sel = self.dev_listbox.curselection()
        if not _skip_sel_check:
            if not sel:
                return
            idx = sel[0]
        else:
            idx = sel[0] if sel else None
            if idx is None:
                return
        dev_id, dev_name = self.pixels[idx]
        self.selected_device = (dev_id, dev_name)
        self.version_label.config(text=f"{dev_name} 支持的 Android 版本：")
        self.name_var.set(f"{dev_id}_android")
        self.selected_api = None
        self.ver_radio_var.set("")
        # 清空版本列表
        for w in self.ver_inner.winfo_children():
            w.destroy()
        self._ver_grid_pos = [0, 0]  # 重置 grid 位置
        # 合并：先取本地 PIXEL_API_RANGE，再考虑在线发现的更高 API
        min_api, max_api = PIXEL_API_RANGE.get(dev_id, (28, 35))
        if self.online_apis:
            online_max = max(self.online_apis)
            if online_max > max_api:
                max_api = online_max
        # 遍历范围：同时要包含本地 ANDROID_VERSIONS + 在线发现的额外 API
        api_list = []
        for a in range(min_api, max_api + 1):
            if self._api_is_available_online(a) or a in ANDROID_VERSIONS:
                api_list.append(a)
        # 再补 online_apis 中单独有但超出范围的（如果是新 Pixel 且 PIXEL_API_RANGE 没覆盖）
        for a in self.online_apis:
            if a >= min_api and a not in api_list:
                api_list.append(a)
        if not api_list:
            api_list = sorted(set(ANDROID_VERSIONS.keys()) | set(self.online_apis))
        api_list = sorted(set(api_list), reverse=True)
        for api in api_list:
            installed = system_image_installed(api)
            self._add_version_row(api, self._label_for_api(api), installed,
                                online_only=(not installed and api in self.online_apis))

    def _add_version_row(self, api, label, installed, online_only=False):
        SQ_SIZE = 180  # 每卡 180x180
        # 计算当前画布宽度下能放几列
        canvas_w = self.ver_canvas.winfo_width()
        if canvas_w < 50:
            canvas_w = 300  # 初始未渲染时的兜底宽度
        cols = max(1, (canvas_w - 12) // (SQ_SIZE + 12))
        cols = max(cols, 1)
        # 跟踪 grid 位置
        if not hasattr(self, "_ver_grid_pos"):
            self._ver_grid_pos = [0, 0]  # [row, col]
        gr, gc = self._ver_grid_pos
        row = tk.Frame(self.ver_inner, bg=CARD, highlightbackground=BORDER,
                       highlightthickness=2, width=SQ_SIZE, height=SQ_SIZE)
        row.grid(row=gr, column=gc, padx=6, pady=6, sticky="nw")
        row.pack_propagate(False)
        # 前进 grid 位置
        gc += 1
        if gc >= cols:
            gc = 0
            gr += 1
        self._ver_grid_pos = [gr, gc]
        # 选中态：蓝色描边
        def refresh_border(*_unused, r=row, a=api):
            if self.ver_radio_var.get() == str(a):
                r.config(highlightbackground=PRIMARY, highlightthickness=2)
            else:
                r.config(highlightbackground=BORDER, highlightthickness=2)
        self.ver_radio_var.trace_add("write", refresh_border)

        # 顶部：API 圆形徽章
        top = tk.Frame(row, bg=CARD)
        top.pack(fill="x", padx=10, pady=(10, 2))
        chip = tk.Label(top, text=f"API {api}", bg=PRIMARY_SOFT, fg=PRIMARY,
                        font=CN_BOLD, padx=8, pady=2, relief="flat", bd=0)
        chip.pack(side="left")
        # 状态
        if installed:
            tk.Label(top, text="✓", bg=CARD, fg=SUCCESS, font=("Microsoft YaHei UI", 14, "bold")).pack(side="right")
        elif online_only:
            tk.Label(top, text="🌐", bg=CARD, fg=ACCENT, font=("Microsoft YaHei UI", 12)).pack(side="right")

        # 中部：Android 版本名称（2行）
        mid = tk.Frame(row, bg=CARD)
        mid.pack(fill="both", expand=True, padx=10, pady=(4, 2))
        tk.Label(mid, text=label, bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 11, "bold"),
                 wraplength=SQ_SIZE - 20, justify="center").pack()
        tk.Label(mid, text=" ", bg=CARD, fg=MUTED, font=CN_SM,
                 wraplength=SQ_SIZE - 20).pack(pady=(2, 0))

        # 底部：选择方框 + 下载/安装状态（等边方框选中指示）
        bottom = tk.Frame(row, bg=CARD)
        bottom.pack(fill="x", padx=10, pady=(4, 10))
        # 等边方框（20x20）作为选中指示（点击整行或方框都能选中）
        box_canvas = tk.Canvas(bottom, width=20, height=20, bg=CARD, highlightthickness=0,
                               bd=0, cursor="hand2")
        box_canvas.pack(side="left")
        def draw_box():
            box_canvas.delete("all")
            sel = self.ver_radio_var.get() == str(api)
            fill = PRIMARY if sel else CARD
            box_canvas.create_rectangle(0, 0, 19, 19, fill=fill,
                                        outline=PRIMARY, width=2)
            if sel:
                box_canvas.create_line(4, 10, 8, 14, 15, 6, fill=PRIMARY_CT, width=3,
                                       capstyle="round", joinstyle="round", smooth=False)
        draw_box()
        self.ver_radio_var.trace_add("write", lambda *_: draw_box())

        def _select_api(*_):
            self.ver_radio_var.set(str(api))
            self._on_version_select(api)
        # 点击方框能选中
        box_canvas.bind("<Button-1>", lambda e: _select_api())
        # 点击行其他位置也能选中
        for w in (row, top, chip, mid, bottom, row):
            try:
                w.bind("<Button-1>", lambda e: _select_api())
            except Exception:
                pass
        # 文字子控件
        for child in row.winfo_children():
            for sub in child.winfo_children():
                try:
                    if not hasattr(sub, "_no_pick"):
                        sub.bind("<Button-1>", lambda e: _select_api())
                except Exception:
                    pass

        # 下载按钮（仅未安装时显示）
        if not installed:
            dl_lbl = tk.Label(bottom, text="⬇ 下载", bg=CARD, fg=ACCENT, font=CN_BOLD,
                              cursor="hand2")
            dl_lbl.pack(side="right")
            dl_lbl.bind("<Button-1>", lambda e, a=api, b=dl_lbl: (self._download_image(a, b), _select_api()))

    def _on_version_select(self, api):
        self.selected_api = api
        self.name_var.set(f"{self.selected_device[0]}_android{api}")

    def _download_image(self, api, btn):
        """用 sdkmanager 下载系统镜像"""
        btn.config(text="下载中…", fg=MUTED)
        pkg = f"system-images;android-{api};google_apis;x86_64"
        self.dlog(f"开始下载 {pkg} …")

        def runner():
            code = run_stream([SDKMANAGER, pkg], self.dlog)
            if code == 0:
                self.dlog(f"✓ {pkg} 下载完成！")
                self.dlog("✓ 已完成!")
                self.installed_apis.add(api)
                self.after(0, lambda: self._refresh_version_row(api, btn))
            else:
                self.dlog(f"✗ 下载失败，退出码 {code}")
                self.after(0, lambda: btn.config(text="⬇ 下载", fg=ACCENT))

        t = threading.Thread(target=runner, daemon=True)
        t.start()
        self._download_threads.add(t)

    def _refresh_version_row(self, api, btn):
        """下载完成后刷新该行的状态标签"""
        parent = btn.master
        btn.destroy()
        tk.Label(parent, text="✓ 已安装", bg=CARD, fg=SUCCESS, font=CN_SM).pack(side="right")

    def _relayout_version_cards(self):
        """窗口大小变化时重新排列版本卡片 grid。"""
        SQ_SIZE = 180
        canvas_w = self.ver_canvas.winfo_width()
        if canvas_w < 50:
            return
        cols = max(1, (canvas_w - 12) // (SQ_SIZE + 12))
        rows = self.ver_inner.winfo_children()
        for i, child in enumerate(rows):
            r, c = divmod(i, cols)
            try:
                child.grid_configure(row=r, column=c, padx=6, pady=6)
            except Exception:
                pass

    def do_create(self):
        if not self.selected_device:
            messagebox.showwarning("提示", "请先选择 Pixel 机型。", parent=self)
            return
        dev_id, dev_name = self.selected_device
        if self.selected_api is None:
            messagebox.showwarning("提示", "请在右侧选择一个 Android 版本。", parent=self)
            return
        selected_api = self.selected_api
        name = self.name_var.get().strip()
        if not re.match(r"^[A-Za-z0-9_.-]+$", name):
            messagebox.showerror("错误", "名称只能包含字母、数字、下划线、点、短横线。", parent=self)
            return
        if not system_image_installed(selected_api):
            messagebox.showwarning("提示", f"Android {ANDROID_VERSIONS[selected_api]} 的系统镜像尚未下载，请先点击「⬇ 下载」。", parent=self)
            return
        img = f"system-images;android-{selected_api};google_apis;x86_64"
        # 存储位置：用户可单独指定，留空则用默认 AVD 目录
        loc = self.loc_var.get().strip()
        avd_dir = None
        if loc:
            avd_dir = os.path.join(loc, name + ".avd")
            os.makedirs(loc, exist_ok=True)
        self.create_btn.config(state="disabled", text="创建中…")
        self.dlog(f"创建 AVD：{name}")
        self.dlog(f"  设备：{dev_name} ({dev_id})")
        self.dlog(f"  镜像：{img}")
        self.dlog(f"  存储位置：{avd_dir if avd_dir else '（默认 AVD 目录）'}")
        args = [AVDMANAGER, "create", "avd", "-n", name, "-k", img, "-d", dev_id]
        if avd_dir:
            args += ["-p", avd_dir]

        def worker():
            proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
            out, _ = proc.communicate(input=b"no\n", timeout=300)
            text = out.decode("utf-8", errors="replace")
            self.after(0, lambda: self._on_done(proc.returncode, text))

        threading.Thread(target=worker, daemon=True).start()

    def _on_done(self, code, text):
        for line in text.splitlines():
            self.dlog(line)
        if code == 0:
            self.dlog("[成功] AVD 已创建。")
            self.dlog("✓ 已完成!")
            self.after(800, lambda: (self.on_created(), self.destroy()))
        else:
            self.dlog(f"[失败] 退出码 {code}")
            self.create_btn.config(state="normal", text="创建 AVD")


# ============================================================
# 添加 AVD - OTA 包导入
# ============================================================
class OtaImportDialog(tk.Toplevel):
    def __init__(self, master, on_done):
        super().__init__(master)
        self.title("导入 OTA 包")
        self.configure(bg=BG)
        self.transient(master)
        self.grab_set()
        self.on_done = on_done
        self.ota_path = None

        f = tk.Frame(self, bg=BG, padx=24, pady=20)
        f.pack(fill="both", expand=True)
        tk.Label(f, text="导入 OTA 包", bg=BG, fg=TEXT, font=CN_BOLD).pack(anchor="w", pady=(0, 4))
        tk.Label(f, text="选择一个 OTA 更新包（.zip），将启动指定 AVD 到 Recovery 并 sideload 刷入。",
                 bg=BG, fg=MUTED, font=CN_SM, wraplength=420, justify="left").pack(anchor="w", pady=(0, 12))

        # OTA 路径
        path_row = tk.Frame(f, bg=BG)
        path_row.pack(fill="x", pady=(0, 8))
        self.path_var = tk.StringVar()
        self.path_var.set("（未选择）")
        tk.Label(path_row, text="OTA 包：", bg=BG, fg=TEXT, font=CN).pack(side="left")
        tk.Label(path_row, textvariable=self.path_var, bg=BG, fg=MUTED, font=CN_SM).pack(side="left", padx=8)
        make_button(path_row, "浏览…", self._browse, "ghost").pack(side="left")

        # AVD 选择
        avd_row = tk.Frame(f, bg=BG)
        avd_row.pack(fill="x", pady=(0, 12))
        tk.Label(avd_row, text="目标 AVD：", bg=BG, fg=TEXT, font=CN).pack(side="left")
        self.avds = list_avds()
        self.avd_var = tk.StringVar()
        if self.avds:
            self.avd_var.set(self.avds[0][0])
        avd_cb = ttk.Combobox(avd_row, textvariable=self.avd_var,
                              values=[n for (n, _p) in self.avds],
                              font=CN, state="readonly", width=22)
        avd_cb.pack(side="left", padx=8)

        # 日志
        self.log_box = tk.Text(f, font=CN_MONO, height=6, bg=LOG_BG, fg=LOG_FG, bd=0,
                               highlightthickness=1, highlightbackground=BORDER,
                               relief="flat", padx=6, pady=4)
        self.log_box.pack(fill="x", pady=(0, 10))

        # 按钮
        bf = tk.Frame(f, bg=BG)
        bf.pack(fill="x")
        make_button(bf, "取消", self.destroy, "ghost").pack(side="right")
        self.run_btn = make_button(bf, "开始刷入", self._run, "primary")
        self.run_btn.pack(side="right", padx=(0, 8))

        self.geometry("500x420")

    def dlog(self, msg):
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")

    def _browse(self):
        path = filedialog.askopenfilename(
            title="选择 OTA 包",
            filetypes=[("OTA 包", "*.zip"), ("所有文件", "*.*")], parent=self)
        if path:
            self.ota_path = path
            self.path_var.set(os.path.basename(path))

    def _run(self):
        if not self.ota_path:
            messagebox.showwarning("提示", "请先选择 OTA 包。", parent=self)
            return
        avd_name = self.avd_var.get()
        if not avd_name:
            messagebox.showwarning("提示", "请选择目标 AVD。", parent=self)
            return
        self.run_btn.config(state="disabled", text="执行中…")
        self.dlog(f"启动 {avd_name} 并进入 Recovery…")
        self.dlog(f"OTA 包：{self.ota_path}")
        # 启动 AVD
        threading.Thread(target=run_stream,
                         args=([EMULATOR, "-avd", avd_name, "-no-snapshot-load"], self.dlog),
                         daemon=True).start()
        # 等待上线后 reboot recovery 再 sideload
        threading.Thread(target=self._wait_and_sideload, args=(avd_name,), daemon=True).start()

    def _wait_and_sideload(self, avd_name):
        deadline = time.time() + 60
        serial = None
        while time.time() < deadline:
            for s, st in running_devices():
                if st == "device" and boot_completed(s) == "1":
                    serial = s
                    break
            if serial:
                break
            time.sleep(2)
        if not serial:
            self.dlog("[超时] 设备未上线。")
            self.after(0, lambda: self.run_btn.config(state="normal", text="开始刷入"))
            return
        self.dlog(f"设备 {serial} 已上线，进入 Recovery…")
        run_stream([ADB, "-s", serial, "reboot", "recovery"], self.dlog)
        time.sleep(8)
        self.dlog("执行 sideload…")
        code = run_stream([ADB, "-s", serial, "sideload", self.ota_path], self.dlog)
        if code == 0:
            self.dlog("✓ OTA sideload 完成！设备将重启。")
        else:
            self.dlog(f"✗ sideload 失败，退出码 {code}")
        self.after(0, lambda: self.run_btn.config(state="normal", text="开始刷入"))


# ============================================================
# 导入自定义 system-image 并创建 AVD
# ============================================================
class CustomImageImportDialog(tk.Toplevel):
    """导入一个完整的 system-image 目录或 zip 包，自动配置到 SDK 并创建 AVD。

    system-image 目录应至少包含 system.img（以及通常的 ramdisk.img/kernel）。
    用户可指定 API level / tag / ABI / 设备机型 / AVD 名称。
    若缺失 source.properties 会被自动生成。
    """

    def __init__(self, master, on_created):
        super().__init__(master)
        self.title("导入自定义镜像")
        self.configure(bg=BG)
        self.transient(master)
        self.grab_set()
        self.on_created = on_created
        self.source_path = None
        self.source_files = []
        self.devices = list_pixel_devices() or [("pixel_6", "Pixel 6")]

        f = tk.Frame(self, bg=BG, padx=18, pady=16)
        f.pack(fill="both", expand=True)
        tk.Label(f, text="导入自定义 system-image", bg=BG, fg=TEXT,
                 font=CN_BOLD).pack(anchor="w", pady=(0, 4))
        tk.Label(f, text="选择一个包含 system.img（及 ramdisk.img/kernel 等）的目录或 zip 包，"
                 "将自动配置到 SDK system-images 并创建 AVD。",
                 bg=BG, fg=MUTED, font=CN_SM, wraplength=560, justify="left").pack(anchor="w", pady=(0, 12))

        # 1. 源路径
        src_card = tk.Frame(f, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        src_card.pack(fill="x", pady=(0, 8))
        src_inner = tk.Frame(src_card, bg=CARD)
        src_inner.pack(fill="x", padx=10, pady=8)
        tk.Label(src_inner, text="1. 镜像来源", bg=CARD, fg=TEXT, font=CN_BOLD).pack(anchor="w")
        path_row = tk.Frame(src_inner, bg=CARD)
        path_row.pack(fill="x", pady=(4, 0))
        self.src_var = tk.StringVar(value="（未选择）")
        tk.Label(path_row, textvariable=self.src_var, bg=CARD, fg=MUTED, font=CN_SM,
                 anchor="w").pack(side="left", fill="x", expand=True)
        make_button(path_row, "选择目录…", self._browse_dir, "ghost").pack(side="left", padx=(6, 4))
        make_button(path_row, "选择 zip…", self._browse_zip, "ghost").pack(side="left")
        self.detected_label = tk.Label(src_inner, text="", bg=CARD, fg=MUTED, font=CN_SM,
                                      anchor="w", justify="left")
        self.detected_label.pack(anchor="w", pady=(4, 0))

        # 2. 配置项
        cfg_card = tk.Frame(f, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        cfg_card.pack(fill="x", pady=(0, 8))
        cfg = tk.Frame(cfg_card, bg=CARD)
        cfg.pack(fill="x", padx=10, pady=10)
        tk.Label(cfg, text="2. 配置", bg=CARD, fg=TEXT, font=CN_BOLD).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))

        tk.Label(cfg, text="API Level", bg=CARD, fg=TEXT, font=CN).grid(row=1, column=0, sticky="e", padx=(0, 6), pady=4)
        self.api_var = tk.StringVar(value="35")
        tk.Entry(cfg, textvariable=self.api_var, font=CN, width=8, bg=CARD, fg=TEXT,
                 relief="flat", bd=0, highlightthickness=1,
                 highlightbackground=BORDER).grid(row=1, column=1, sticky="w", pady=4, ipady=3)

        tk.Label(cfg, text="Tag", bg=CARD, fg=TEXT, font=CN).grid(row=1, column=2, sticky="e", padx=(16, 6), pady=4)
        self.tag_var = tk.StringVar(value="google_apis")
        ttk.Combobox(cfg, textvariable=self.tag_var, values=["google_apis", "default", "android-automotive", "android-tv", "android-wear"],
                     font=CN, width=16, state="readonly").grid(row=1, column=3, sticky="w", pady=4)

        tk.Label(cfg, text="ABI", bg=CARD, fg=TEXT, font=CN).grid(row=2, column=0, sticky="e", padx=(0, 6), pady=4)
        self.abi_var = tk.StringVar(value="x86_64")
        ttk.Combobox(cfg, textvariable=self.abi_var, values=["x86_64", "arm64-v8a", "x86"],
                     font=CN, width=8, state="readonly").grid(row=2, column=1, sticky="w", pady=4)

        tk.Label(cfg, text="设备机型", bg=CARD, fg=TEXT, font=CN).grid(row=2, column=2, sticky="e", padx=(16, 6), pady=4)
        self.dev_var = tk.StringVar()
        dev_names = [n for (_i, n) in self.devices]
        if dev_names:
            self.dev_var.set("Pixel 6")
        ttk.Combobox(cfg, textvariable=self.dev_var, values=dev_names,
                     font=CN, width=16, state="readonly").grid(row=2, column=3, sticky="w", pady=4)

        tk.Label(cfg, text="AVD 名称", bg=CARD, fg=TEXT, font=CN).grid(row=3, column=0, sticky="e", padx=(0, 6), pady=4)
        self.name_var = tk.StringVar(value="CustomAVD")
        tk.Entry(cfg, textvariable=self.name_var, font=CN, width=20, bg=CARD, fg=TEXT,
                 relief="flat", bd=0, highlightthickness=1,
                 highlightbackground=BORDER).grid(row=3, column=1, columnspan=3, sticky="we", pady=4, ipady=3)

        # 存储位置（每台 AVD 可单独指定）
        tk.Label(cfg, text="存储位置", bg=CARD, fg=TEXT, font=CN).grid(row=4, column=0, sticky="e", padx=(0, 6), pady=4)
        self.loc_var = tk.StringVar(value=AVD_USER_HOME)
        tk.Entry(cfg, textvariable=self.loc_var, font=CN, width=28, bg=CARD, fg=TEXT,
                 relief="flat", bd=0, highlightthickness=1,
                 highlightbackground=BORDER).grid(row=4, column=1, columnspan=2, sticky="we", pady=4, ipady=3)
        make_button(cfg, "📂 浏览…", self._browse_loc, "ghost").grid(row=4, column=3, sticky="w", padx=(4, 0), pady=4)

        # 3. 日志
        self.log_box = tk.Text(f, font=CN_MONO, height=7, bg=LOG_BG, fg=LOG_FG, bd=0,
                               highlightthickness=1, highlightbackground=BORDER,
                               relief="flat", padx=6, pady=4)
        self.log_box.pack(fill="both", expand=True, pady=(8, 8))

        # 按钮
        bf = tk.Frame(f, bg=BG)
        bf.pack(fill="x")
        make_button(bf, "取消", self.destroy, "ghost").pack(side="right")
        self.import_btn = make_button(bf, "导入并创建 AVD", self.do_import, "primary")
        self.import_btn.pack(side="right", padx=(0, 8))

        self.geometry("640x560")

    def dlog(self, msg):
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")

    def _browse_dir(self):
        path = filedialog.askdirectory(title="选择 system-image 目录", parent=self)
        if path:
            self.source_path = path
            self.src_var.set(path)
            self._detect_source()

    def _browse_zip(self):
        path = filedialog.askopenfilename(
            title="选择 system-image zip 包",
            filetypes=[("ZIP 包", "*.zip"), ("所有文件", "*.*")], parent=self)
        if path:
            self.source_path = path
            self.src_var.set(path)
            self._detect_source()

    def _scan_dir_for_images(self, directory):
        """在目录（含子目录）中查找镜像文件，返回 {abs_path: rel_name}"""
        found = {}
        targets = ("system.img", "ramdisk.img", "kernel", "userdata.img",
                   "boot.img", "vbmeta.img", "source.properties", "build.prop")
        for root, _dirs, files in os.walk(directory):
            for fn in files:
                if fn in targets or fn.endswith(".img"):
                    found[os.path.join(root, fn)] = fn
        return found

    def _detect_source(self):
        """检测源目录/zip 是否含必要文件，尝试自动推断 API/tag/abi"""
        self.source_files = []
        if not self.source_path:
            return
        is_zip = self.source_path.lower().endswith(".zip")
        if is_zip:
            # 扫描 zip 内文件名
            try:
                import zipfile
                zf = zipfile.ZipFile(self.source_path)
                names = zf.namelist()
                zf.close()
            except Exception as e:
                self.detected_label.config(text=f"[无法读取 zip] {e}", fg=DANGER)
                return
            targets = ("system.img", "ramdisk.img", "kernel", "userdata.img",
                       "source.properties", "build.prop")
            found = [os.path.basename(n) for n in names
                     if os.path.basename(n) in targets or n.endswith(".img")]
            self.source_files = sorted(set(found))
        else:
            if not os.path.isdir(self.source_path):
                self.detected_label.config(text="[路径不存在]", fg=DANGER)
                return
            found = self._scan_dir_for_images(self.source_path)
            self.source_files = sorted(set(found.values()))

        has_system = "system.img" in self.source_files
        if not has_system:
            self.detected_label.config(
                text=f"⚠ 未找到 system.img\n检测到的镜像文件：{', '.join(self.source_files) or '无'}",
                fg=WARN)
            return

        # 尝试从 source.properties / build.prop 自动推断
        self._try_infer_from_props(is_zip)
        self.detected_label.config(
            text=f"✓ 检测到 {len(self.source_files)} 个相关文件：\n{', '.join(self.source_files[:8])}" +
                 (" …" if len(self.source_files) > 8 else ""),
            fg=SUCCESS)

    def _try_infer_from_props(self, is_zip):
        """从 source.properties / build.prop 读取 API/Tag/ABI"""
        props = {}
        if is_zip:
            import zipfile
            try:
                zf = zipfile.ZipFile(self.source_path)
                for name in zf.namelist():
                    base = os.path.basename(name)
                    if base in ("source.properties", "build.prop"):
                        try:
                            props.update(self._parse_props(zf.read(name).decode("utf-8", errors="replace")))
                        except Exception:
                            pass
                zf.close()
            except Exception:
                pass
        else:
            for cand in ("source.properties", "build.prop"):
                # 在源目录及子目录查找
                for root, _dirs, files in os.walk(self.source_path):
                    if cand in files:
                        try:
                            with open(os.path.join(root, cand), "r", encoding="utf-8", errors="replace") as fp:
                                props.update(self._parse_props(fp.read()))
                        except Exception:
                            pass
        if props:
            api = props.get("AndroidVersion.ApiLevel") or props.get("ro.build.version.sdk")
            if api:
                self.api_var.set(str(api))
            tag = props.get("SystemImage.Tag") or props.get("ro.product.system.tag")
            if tag:
                self.tag_var.set(tag)
            abi = props.get("SystemImage.Abi") or props.get("ro.product.cpu.abi")
            if abi:
                self.abi_var.set(abi)
            name = props.get("Pkg.Revision", "")
            rev = name.split(".")[-1] if name else ""
            if rev:
                self.name_var.set(f"CustomAVD_api{self.api_var.get()}")

    @staticmethod
    def _parse_props(text):
        """解析 key=value 格式的属性文件"""
        result = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                result[k.strip()] = v.strip()
        return result

    def do_import(self):
        if not self.source_path:
            messagebox.showwarning("提示", "请先选择镜像来源（目录或 zip）。", parent=self)
            return
        if "system.img" not in self.source_files:
            messagebox.showwarning("提示", "未检测到 system.img，无法导入。", parent=self)
            return
        try:
            api = int(self.api_var.get())
        except ValueError:
            messagebox.showerror("错误", "API Level 必须是数字。", parent=self)
            return
        tag = self.tag_var.get().strip() or "google_apis"
        abi = self.abi_var.get().strip() or "x86_64"
        name = self.name_var.get().strip()
        if not re.match(r"^[A-Za-z0-9_.-]+$", name):
            messagebox.showerror("错误", "AVD 名称只能包含字母、数字、下划线、点、短横线。", parent=self)
            return
        dev_name = self.dev_var.get()
        dev_id = next((i for (i, n) in self.devices if n == dev_name), dev_name)
        dest = os.path.join(SDK_HOME, "system-images", f"android-{api}", tag, abi)

        if os.path.exists(dest):
            if not messagebox.askyesno("目标已存在",
                    f"目标目录已存在：\n{dest}\n\n是否覆盖？现有文件将被替换。", parent=self):
                return

        # AVD 存储位置：用户可单独指定
        loc = self.loc_var.get().strip()
        avd_dir = None
        if loc:
            avd_dir = os.path.join(loc, name + ".avd")
            os.makedirs(loc, exist_ok=True)

        self.import_btn.config(state="disabled", text="导入中…")
        self.dlog(f"目标目录：{dest}")
        self.dlog(f"设备：{dev_name} ({dev_id})  AVD：{name}")
        self.dlog(f"存储位置：{avd_dir if avd_dir else '（默认 AVD 目录）'}")

        threading.Thread(target=self._import_worker,
                         args=(self.source_path, dest, api, tag, abi, name, dev_id, avd_dir),
                         daemon=True).start()

    def _browse_loc(self):
        p = filedialog.askdirectory(title="选择 AVD 存储位置",
                                     initialdir=self.loc_var.get() or AVD_USER_HOME,
                                     parent=self)
        if p:
            self.loc_var.set(p)

    def _import_worker(self, src, dest, api, tag, abi, name, dev_id, avd_dir):
        """后台执行：复制/解压 -> 生成 source.properties -> 创建 AVD"""
        try:
            os.makedirs(dest, exist_ok=True)
            # 1. 复制或解压文件
            if src.lower().endswith(".zip"):
                self.dlog(f"解压 zip 到 {dest} …")
                import zipfile
                zf = zipfile.ZipFile(src)
                zf.extractall(dest)
                zf.close()
                self.dlog("✓ 解压完成")
            else:
                self.dlog(f"复制目录内容到 {dest} …")
                # 复制扫描到的镜像相关文件（保持扁平结构到 dest）
                found = self._scan_dir_for_images(src)
                # 若源目录直接是 system-image 根（含 system.img），直接复制全部
                # 否则只复制扫描到的文件
                top_files = [f for f in os.listdir(src)
                             if os.path.isfile(os.path.join(src, f))]
                if "system.img" in top_files:
                    # 直接复制该目录所有文件
                    import shutil
                    for fn in top_files:
                        s = os.path.join(src, fn)
                        d = os.path.join(dest, fn)
                        self.dlog(f"  复制 {fn} …")
                        shutil.copy2(s, d)
                else:
                    import shutil
                    for abs_p, fn in found.items():
                        d = os.path.join(dest, fn)
                        self.dlog(f"  复制 {fn} …")
                        shutil.copy2(abs_p, d)
                self.dlog("✓ 复制完成")

            # 2. 确保 source.properties 存在
            sp = os.path.join(dest, "source.properties")
            if not os.path.exists(sp):
                self.dlog("生成 source.properties …")
                with open(sp, "w", encoding="utf-8") as wf:
                    wf.write("Pkg.Desc=Custom Android System Image\n")
                    wf.write(f"Pkg.Revision=1\n")
                    wf.write(f"AndroidVersion.ApiLevel={api}\n")
                    wf.write(f"SystemImage.Abi={abi}\n")
                    wf.write(f"SystemImage.TagId={tag}\n")
                self.dlog("✓ 已生成 source.properties")

            # 3. 创建 AVD
            pkg_id = f"system-images;android-{api};{tag};{abi}"
            self.dlog(f"创建 AVD：{name}  镜像：{pkg_id}")
            args = [AVDMANAGER, "create", "avd", "-n", name, "-k", pkg_id, "-d", dev_id]
            if avd_dir:
                args += ["-p", avd_dir]
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
            out, _ = proc.communicate(input=b"no\n", timeout=300)
            text = out.decode("utf-8", errors="replace")
            self.after(0, lambda: self._on_done(proc.returncode, text, name))
        except Exception as e:
            self.after(0, lambda: self._on_done(-1, f"[导入异常] {e}", name))

    def _on_done(self, code, text, name):
        for line in text.splitlines():
            self.dlog(f"  {line}")
        if code == 0:
            self.dlog(f"✓ 导入并创建 AVD「{name}」成功！")
            self.after(1000, lambda: (self.on_created(), self.destroy()))
        else:
            self.dlog(f"✗ 失败，退出码 {code}")
            self.import_btn.config(state="normal", text="导入并创建 AVD")


# ============================================================
# 快照管理窗口（保存/恢复 AVD 运行状态）
# ============================================================
class SnapshotDialog(tk.Toplevel):
    """通过 `adb emu avd snapshot` 管理模拟器运行状态快照。

    快照保存的是模拟器当前的内存与运行状态，加载快照可瞬间恢复到该状态，
    无需重启 Android。与"备份 AVD"（打包磁盘文件）不同：快照适合保存
    "某个运行到一半的状态"，重启后会丢失，但加载极快。
    """

    def __init__(self, master, device):
        super().__init__(master)
        self.title(f"快照管理 - {device}")
        self.configure(bg=BG)
        self.transient(master)
        self.grab_set()
        self.device = device
        self.selected_snap = None  # 当前选中的快照名
        self._last_snaps = []      # 上次解析到的快照列表

        f = tk.Frame(self, bg=BG, padx=18, pady=16)
        f.pack(fill="both", expand=True)
        tk.Label(f, text="📸 AVD 运行状态快照", bg=BG, fg=TEXT,
                 font=CN_BOLD).pack(anchor="w", pady=(0, 4))
        tk.Label(f, text="快照保存模拟器当前的内存与运行状态。加载快照可瞬间恢复到该状态。\n"
                 "注意：快照保存在 AVD 目录下，删除 AVD 会一并删除其快照。",
                 bg=BG, fg=MUTED, font=CN_SM, wraplength=560, justify="left").pack(anchor="w", pady=(0, 12))

        # 快照流程区（横向滚动，卡片间用 → 连接）
        list_card = tk.Frame(f, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        list_card.pack(fill="both", expand=True, pady=(0, 8))
        list_inner = tk.Frame(list_card, bg=CARD)
        list_inner.pack(fill="both", expand=True, padx=10, pady=10)

        tk.Label(list_inner, text="现有快照（点击选中）", bg=CARD, fg=TEXT,
                 font=CN_BOLD).pack(anchor="w", pady=(0, 6))

        # Canvas + 横向滚动条承载流程
        flow_frame = tk.Frame(list_inner, bg=CARD)
        flow_frame.pack(fill="both", expand=True)
        self.flow_canvas = tk.Canvas(flow_frame, bg=CARD, highlightthickness=0, height=120)
        hsb = ttk.Scrollbar(flow_frame, orient="horizontal", command=self.flow_canvas.xview)
        self.flow_canvas.pack(side="top", fill="both", expand=True)
        hsb.pack(side="bottom", fill="x")
        self.flow_canvas.config(xscrollcommand=hsb.set)
        self.flow_inner = tk.Frame(self.flow_canvas, bg=CARD)
        self.flow_canvas.create_window((0, 0), window=self.flow_inner, anchor="nw")
        self.flow_inner.bind("<Configure>",
                             lambda e: self.flow_canvas.configure(scrollregion=self.flow_canvas.bbox("all")))

        # 保存新快照
        save_card = tk.Frame(f, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        save_card.pack(fill="x", pady=(0, 8))
        save_inner = tk.Frame(save_card, bg=CARD)
        save_inner.pack(fill="x", padx=10, pady=8)
        tk.Label(save_inner, text="💾 保存当前状态为快照", bg=CARD, fg=TEXT, font=CN_BOLD).pack(anchor="w")
        row = tk.Frame(save_inner, bg=CARD)
        row.pack(fill="x", pady=(4, 0))
        tk.Label(row, text="名称", bg=CARD, fg=TEXT, font=CN).pack(side="left", padx=(0, 6))
        self.name_var = tk.StringVar(value="snap_" + time.strftime("%m%d_%H%M%S"))
        tk.Entry(row, textvariable=self.name_var, font=CN, width=22, bg=CARD, fg=TEXT,
                 relief="flat", bd=0, highlightthickness=1,
                 highlightbackground=BORDER).pack(side="left", padx=(0, 8), ipady=3)
        make_button(row, "💾 保存快照", self.save_snapshot, "primary").pack(side="left")
        make_button(row, "🔄 刷新", self.refresh, "ghost").pack(side="left", padx=(6, 0))

        # 选中快照操作
        op_row = tk.Frame(f, bg=BG)
        op_row.pack(fill="x", pady=(4, 8))
        self.sel_label = tk.Label(op_row, text="未选中快照", bg=BG, fg=MUTED, font=CN)
        self.sel_label.pack(side="left")
        make_button(op_row, "▶ 加载快照", self.load_snapshot, "success").pack(side="right")
        make_button(op_row, "🗑 删除快照", self.delete_snapshot, "danger").pack(side="right", padx=(0, 6))

        # 日志
        tk.Label(f, text="📝 操作日志", bg=BG, fg=MUTED, font=CN_SM).pack(anchor="w", pady=(4, 2))
        self.log_box = tk.Text(f, font=CN_MONO, height=6, bg=LOG_BG, fg=LOG_FG, bd=0,
                               highlightthickness=1, highlightbackground=BORDER,
                               relief="flat", padx=6, pady=4)
        self.log_box.pack(fill="x", pady=(0, 8))

        bf = tk.Frame(f, bg=BG)
        bf.pack(fill="x")
        make_button(bf, "关闭", self.destroy, "ghost").pack(side="right")

        self.geometry("720x560")
        self.after(200, self.refresh)

    def dlog(self, msg):
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")

    def _selected_name(self):
        if not self.selected_snap:
            messagebox.showwarning("提示", "请先点击一个快照卡片以选中。", parent=self)
            return None
        return self.selected_snap

    def _select_snap(self, name):
        """选中某个快照卡片，高亮并更新状态"""
        self.selected_snap = name
        self.sel_label.config(text=f"已选中：{name}", fg=ACCENT)
        # 重新渲染以更新高亮
        self._render_snaps(self._last_snaps)

    # ----- 后台命令执行 -----
    def _run_emu_cmd(self, args, on_done_msg):
        """后台执行 `adb emu avd snapshot ...` 命令"""
        cmd = [ADB, "-s", self.device, "emu", "avd", "snapshot"] + args

        def worker():
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                out, _ = proc.communicate(timeout=120)
                text = out.decode("utf-8", errors="replace")
                self.after(0, lambda: self._on_cmd_done(proc.returncode, text, on_done_msg))
            except subprocess.TimeoutExpired:
                proc.kill()
                self.after(0, lambda: self._on_cmd_done(-1, "[超时] 命令执行超过 120 秒", on_done_msg))
            except Exception as e:
                self.after(0, lambda: self._on_cmd_done(-1, f"[异常] {e}", on_done_msg))

        threading.Thread(target=worker, daemon=True).start()

    def _on_cmd_done(self, code, text, done_msg):
        for line in text.splitlines():
            line = line.strip()
            if line:
                self.dlog(f"  {line}")
        if code == 0 and done_msg:
            self.dlog(done_msg)
            self.after(500, self.refresh)
        else:
            self.dlog(f"✗ 退出码 {code}")

    # ----- 快照操作 -----
    def save_snapshot(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "请输入快照名称。", parent=self)
            return
        if not re.match(r"^[A-Za-z0-9_.\-]+$", name):
            messagebox.showerror("错误", "名称只能包含字母、数字、下划线、点、短横线。", parent=self)
            return
        self.dlog(f"保存快照：{name} …")
        self._run_emu_cmd(["save", name], f"✓ 快照「{name}」已保存。")

    def load_snapshot(self):
        name = self._selected_name()
        if not name:
            return
        if not messagebox.askyesno("确认加载",
                f"加载快照「{name}」将使模拟器恢复到该快照的状态。\n"
                "当前未保存的运行状态将丢失。是否继续？", parent=self):
            return
        self.dlog(f"加载快照：{name} …")
        self._run_emu_cmd(["load", name], f"✓ 快照「{name}」已加载。")

    def delete_snapshot(self):
        name = self._selected_name()
        if not name:
            return
        if not messagebox.askyesno("确认删除",
                f"确定删除快照「{name}」吗？此操作不可恢复。", parent=self):
            return
        self.dlog(f"删除快照：{name} …")
        self._run_emu_cmd(["delete", name], f"✓ 快照「{name}」已删除。")

    def refresh(self):
        self.dlog("刷新快照列表 …")
        cmd = [ADB, "-s", self.device, "emu", "avd", "snapshot", "list"]

        def worker():
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                out, _ = proc.communicate(timeout=30)
                text = out.decode("utf-8", errors="replace")
                self.after(0, lambda: self._on_list_done(proc.returncode, text))
            except Exception as e:
                self.after(0, lambda: self._on_list_done(-1, f"[异常] {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_list_done(self, code, text):
        snapshots = parse_snapshot_list(text)
        self._last_snaps = snapshots
        if snapshots:
            self._render_snaps(snapshots)
            self.dlog(f"✓ 共 {len(snapshots)} 个快照。")
        else:
            # 输出原始内容供调试
            self._clear_flow()
            empty = tk.Label(self.flow_inner, text="🤖 暂无快照\n\n点击上方「💾 保存快照」创建第一个",
                             bg=CARD, fg=MUTED, font=CN, justify="center")
            empty.pack(padx=20, pady=20)
            for line in text.splitlines():
                line = line.strip()
                if line:
                    self.dlog(f"  {line}")

    def _clear_flow(self):
        """清空流程区"""
        for w in self.flow_inner.winfo_children():
            w.destroy()

    def _render_snaps(self, snapshots):
        """以「快照名 → 快照名 → ...」流程式渲染快照卡片"""
        self._clear_flow()
        row = tk.Frame(self.flow_inner, bg=CARD)
        row.pack(anchor="w", padx=8, pady=8)
        for idx, (name, size, date) in enumerate(snapshots):
            # 卡片
            is_sel = (name == self.selected_snap)
            bg = ACCENT_SOFT if is_sel else "#28292C"
            border = ACCENT if is_sel else BORDER
            card = tk.Frame(row, bg=bg, highlightbackground=border, highlightthickness=2, bd=0)
            card.pack(side="left", padx=(0, 4), pady=2)
            # 快照名
            tk.Label(card, text=name, bg=bg, fg=TEXT, font=CN_BOLD,
                    padx=14, pady=(8, 2)).pack()
            # 创建时间（快照名下方）
            date_text = date if date else "—"
            tk.Label(card, text=date_text, bg=bg, fg=MUTED, font=CN_SM,
                     padx=14, pady=(0, 2)).pack()
            # 大小
            if size:
                tk.Label(card, text=f"💾 {size}", bg=bg, fg=MUTED, font=CN_SM,
                         padx=14, pady=(0, 8)).pack()
            else:
                tk.Label(card, text="", bg=bg).pack()
            # 点击选中
            def _on_click(e, n=name):
                self._select_snap(n)
            for w in card.winfo_children():
                w.bind("<Button-1>", _on_click)
            card.bind("<Button-1>", _on_click)
            # 箭头连接符（最后一个不加）
            if idx < len(snapshots) - 1:
                tk.Label(row, text="→", bg=CARD, fg=ACCENT, font=CN_BOLD,
                         padx=4).pack(side="left")


# ============================================================
# Magisk Root 任务
# ============================================================
class MagiskRootJob:
    def __init__(self, app, avd_name):
        self.app = app
        self.avd_name = avd_name
        self.log = app.log
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        log = self.log
        log("==== Magisk Root 开始 ====")
        avds = list_avds()
        avd_path = next((p for (n, p) in avds if n == self.avd_name), None)
        if not avd_path:
            log(f"[错误] 找不到 AVD 路径：{self.avd_name}")
            return
        ramdisk = os.path.join(avd_path, "ramdisk.img")
        if not os.path.exists(ramdisk):
            found = None
            base = os.path.join(SDK_HOME, "system-images")
            for root, _dirs, files in os.walk(base):
                if "ramdisk.img" in files:
                    found = os.path.join(root, "ramdisk.img")
                    break
            if not found:
                log("[错误] 未找到任何 ramdisk.img。")
                return
            ramdisk = found
        log(f"ramdisk: {ramdisk}")

        os.makedirs(ROOTAVD_DIR, exist_ok=True)
        rootsh = os.path.join(ROOTAVD_DIR, "rootAVD.sh")
        rootavd_urls = [
            "https://raw.githubusercontent.com/newbit1/rootAVD/master/rootAVD.sh",
            "https://cdn.jsdelivr.net/gh/newbit1/rootAVD@master/rootAVD.sh",
            "https://fastly.jsdelivr.net/gh/newbit1/rootAVD@master/rootAVD.sh",
        ]
        if not (os.path.exists(rootsh) and os.path.getsize(rootsh) > 0):
            ok = False
            for u in rootavd_urls:
                if ensure_downloaded(u, rootsh, log):
                    ok = True
                    break
                if os.path.exists(rootsh):
                    try:
                        os.remove(rootsh)
                    except Exception:
                        pass
            if not ok:
                log("[错误] 下载 rootAVD.sh 失败。")
                return
        else:
            log(f"已存在：{rootsh}")

        apk = os.path.join(ROOTAVD_DIR, "magisk.apk")
        if not (os.path.exists(apk) and os.path.getsize(apk) > 1024 * 1024):
            url = latest_magisk_apk_url(log)
            if not url or not ensure_downloaded(url, apk, log):
                log("[错误] 下载 Magisk APK 失败。")
                return
        else:
            log(f"已存在 Magisk APK：{apk}")

        env = os.environ.copy()
        env["ANDROID_HOME"] = SDK_HOME
        env["ANDROID_SDK_ROOT"] = SDK_HOME
        bash_ramdisk = win_to_bash_path(ramdisk)
        bash_rootdir = win_to_bash_path(ROOTAVD_DIR)
        log(f"bash ramdisk 路径：{bash_ramdisk}")

        wrapper = os.path.join(ROOTAVD_DIR, "_run_rootavd.sh")
        with open(wrapper, "w", newline="\n") as wf:
            wf.write("#!/usr/bin/env bash\n")
            wf.write(f'cd "{bash_rootdir}" || exit 1\n')
            wf.write(f'export ANDROID_HOME="{win_to_bash_path(SDK_HOME)}"\n')
            wf.write(f'export PATH="{win_to_bash_path(os.path.join(SDK_HOME, "platform-tools"))}":$PATH\n')
            wf.write(f'bash rootAVD.sh "{bash_ramdisk}"\n')
            wf.write('echo "[rootAVD 退出码 $?]"\n')

        log("通过 Git Bash 执行 rootAVD.sh …")

        def runner():
            code = run_stream([GIT_BASH, wrapper], log, env=env, cwd=ROOTAVD_DIR)
            log(f"==== Magisk Root 完成，退出码 {code} ====")
            if code == 0:
                log("建议：关闭并重新启动该 AVD（冷启动）以使 Magisk 生效。")

        threading.Thread(target=runner, daemon=True).start()


# ============================================================
# AVD 内部文件浏览器（通过 adb 访问运行中模拟器的文件系统）
# ============================================================
class InternalFileBrowser(tk.Toplevel):
    """简单的模拟器内部文件浏览器：列目录、进入子目录、下载到本地。

    能力：
     - /sdcard、/data/local/tmp、/ 等任意 adb 可访问的目录
     - 双击目录进入、双击文件用 adb pull 下载到临时目录后打开
     - 右键：下载单个文件 / 打开父目录
    """

    def __init__(self, master, serial, avd_name=None, log_fn=None):
        super().__init__(master)
        self.title(f"AVD 内部文件 — {avd_name or serial}（{serial}）")
        self.configure(bg=BG)
        self.transient(master)
        self.serial = serial
        self.avd_name = avd_name
        self.log_fn = log_fn or (lambda m: None)
        self.current_dir = "/sdcard"
        self._files = []  # [(name, is_dir, raw)]

        f = tk.Frame(self, bg=BG, padx=18, pady=16)
        f.pack(fill="both", expand=True)

        # 顶部：路径栏 + 快捷目录
        top_bar = tk.Frame(f, bg=BG)
        top_bar.pack(fill="x", pady=(0, 8))
        tk.Label(top_bar, text="📁 路径：", bg=BG, fg=TEXT_SOFT, font=CN).pack(side="left")
        self.path_var = tk.StringVar(value=self.current_dir)
        entry = tk.Entry(top_bar, textvariable=self.path_var, font=CN, bg=CARD, fg=TEXT,
                         relief="flat", bd=0, highlightthickness=1,
                         highlightbackground=BORDER)
        entry.pack(side="left", fill="x", expand=True, padx=(4, 6), ipady=3)
        entry.bind("<Return>", lambda e: self.cd(self.path_var.get().strip()))
        make_button(top_bar, "前往", lambda: self.cd(self.path_var.get().strip()),
                    "primary", padx=12, pady=4, radius=4).pack(side="left")
        make_button(top_bar, "⬆ 上级", self.cd_parent, "ghost",
                    padx=12, pady=4, radius=4).pack(side="left", padx=6)

        # 快捷目录 Chip
        shortcuts = tk.Frame(f, bg=BG)
        shortcuts.pack(fill="x", pady=(0, 6))
        for label, target in [("📱 /sdcard", "/sdcard"),
                              ("📷 /sdcard/DCIM", "/sdcard/DCIM"),
                              ("📥 /sdcard/Download", "/sdcard/Download"),
                              ("📦 /data/local/tmp", "/data/local/tmp"),
                              ("🔧 /", "/")]:
            chip = tk.Label(shortcuts, text=label, bg=CHIP_GRAY, fg=TEXT,
                            font=CN_SM, padx=8, pady=3,
                            highlightbackground=BORDER, highlightthickness=1,
                            cursor="hand2")
            chip.pack(side="left", padx=(0, 6))
            chip.bind("<Button-1>", lambda e, t=target: self.cd(t))

        # 文件列表卡片
        list_card = make_card(f, padx=14, pady=10)
        list_card.pack(fill="both", expand=True, pady=(4, 8))
        inner = pack_card(list_card)
        head = tk.Frame(inner, bg=CARD)
        head.pack(fill="x", pady=(0, 4))
        tk.Label(head, text="名称", bg=CARD, fg=TEXT, font=CN_BOLD, anchor="w", width=34).pack(side="left")
        tk.Label(head, text="类型", bg=CARD, fg=MUTED, font=CN_SM, anchor="w", width=8).pack(side="left")
        tk.Label(head, text="大小", bg=CARD, fg=MUTED, font=CN_SM, anchor="w", width=12).pack(side="left")
        tk.Label(head, text="时间", bg=CARD, fg=MUTED, font=CN_SM, anchor="w", width=18).pack(side="left")
        # Listbox + 滚动条
        body = tk.Frame(inner, bg=CARD)
        body.pack(fill="both", expand=True)
        self.tree_scroll = ttk.Scrollbar(body)
        self.tree_scroll.pack(side="right", fill="y")
        self.tree = ttk.Treeview(body, columns=("type", "size", "time"), show="tree headings",
                                 selectmode="browse")
        self.tree.heading("#0", text="名称")
        self.tree.heading("type", text="类型")
        self.tree.heading("size", text="大小")
        self.tree.heading("time", text="时间")
        self.tree.column("#0", width=380, anchor="w")
        self.tree.column("type", width=70, anchor="w")
        self.tree.column("size", width=100, anchor="e")
        self.tree.column("time", width=170, anchor="w")
        style = ttk.Style()
        try:
            style.configure("Treeview", rowheight=26, background=CARD, foreground=TEXT, font=CN,
                            fieldbackground=CARD)
            style.map("Treeview", background=[("selected", PRIMARY_SOFT)],
                      foreground=[("selected", PRIMARY)])
        except Exception:
            pass
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.config(yscrollcommand=self.tree_scroll.set)
        self.tree_scroll.config(command=self.tree.yview)
        self.tree.bind("<Double-1>", self._on_row_dblclick)
        # 右键菜单
        self.ctx_menu = tk.Menu(self.tree, tearoff=0, bg=CARD, fg=TEXT,
                                activebackground=PRIMARY_SOFT, activeforeground=PRIMARY,
                                relief="flat", bd=0, font=CN)
        self.ctx_menu.add_command(label="⬇ 下载到本地", command=self._ctx_download)
        self.ctx_menu.add_command(label="📁 在本地文件夹显示已下载", command=self._open_download_dir)
        self.ctx_menu.add_separator()
        self.ctx_menu.add_command(label="🔄 刷新", command=self.refresh)
        self.tree.bind("<Button-3>", self._on_tree_rightclick)

        # 底部按钮
        bot = tk.Frame(f, bg=BG)
        bot.pack(fill="x")
        self.status_lbl = tk.Label(bot, text="加载中…", bg=BG, fg=MUTED, font=CN_SM, anchor="w")
        self.status_lbl.pack(side="left")
        make_button(bot, "🔄 刷新", self.refresh, "ghost", padx=12, pady=4, radius=4).pack(side="right")
        make_button(bot, "⬇ 下载选中文件", self._ctx_download, "primary",
                    padx=12, pady=4, radius=4).pack(side="right", padx=(0, 8))

        self.download_dir = os.path.join(
            os.path.expanduser("~"), "Downloads", "TraeAVD_Pull")
        os.makedirs(self.download_dir, exist_ok=True)

        self.geometry("860x640")
        self.after(50, self.refresh)

    # ---------- adb helpers ----------
    def _adb(self, args, timeout=30):
        """执行 adb -s <serial> <args>，返回 (exit_code, stdout_text)。"""
        full = [ADB, "-s", self.serial] + list(args)
        try:
            proc = subprocess.run(full, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  timeout=timeout,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
            return proc.returncode, proc.stdout.decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            return -1, "[超时] adb 命令超过 %ds" % timeout
        except Exception as e:
            return -1, f"[错误] {e}"

    # ---------- 导航 ----------
    def cd(self, new_dir):
        """切换目录（若指向文件则下载）"""
        if not new_dir:
            return
        new_dir = new_dir.replace("\\", "/")
        # 先尝试列目录
        code, out = self._adb(["shell", "ls", "-la", new_dir])
        if code != 0:
            # 可能是文件 → 直接下载
            code2, _out2 = self._adb(["shell", "ls", new_dir])
            if code2 == 0 and "No such file" not in _out2:
                self.status_lbl.config(text="这是文件，开始下载…", fg=ACCENT)
                self._pull_file(new_dir, open_after=True)
                return
            self.status_lbl.config(text=f"无法进入：{new_dir}", fg=DANGER)
            return
        # 规范化末尾斜杠
        if new_dir != "/" and new_dir.endswith("/"):
            new_dir = new_dir[:-1]
        self.current_dir = new_dir
        self.path_var.set(new_dir)
        self.log_fn(f"[文件浏览] cd {new_dir}")
        self.refresh()

    def cd_parent(self):
        if self.current_dir == "/":
            return
        parent = "/".join(self.current_dir.split("/")[:-1]) or "/"
        self.cd(parent)

    def _parse_ls(self, out, dir_path):
        """解析 `ls -la <dir>` 输出为 [(name, is_dir, size, time)]。"""
        rows = []
        for line in out.splitlines():
            line = line.rstrip()
            if not line:
                continue
            # 跳过 total 行
            if line.startswith("total "):
                continue
            # ls -la 格式（emulator toybox/coreutils）：
            # drwxrwxr-x  2 root sdcard_rw 4096 2025-01-01 00:00 .
            parts = line.split(None, 7)
            if len(parts) < 7:
                continue
            perms, _links, _owner, _group, size, d1, d2, *rest = parts
            if rest:
                name = rest[0]
            else:
                continue
            if name in (".", ".."):
                continue
            is_dir = perms.startswith("d")
            # size 可能为 "0"、"4096"，或 socket/link 的 "?"
            try:
                size_int = int(size)
            except Exception:
                size_int = 0
            tstr = f"{d1} {d2}"
            full = dir_path + "/" + name if dir_path != "/" else "/" + name
            rows.append((name, is_dir, size_int, tstr, full))
        return rows

    # ---------- 渲染 ----------
    def refresh(self):
        self.status_lbl.config(text=f"读取 {self.current_dir} …", fg=WARN)
        self.update_idletasks()

        def worker():
            code, out = self._adb(["shell", "ls", "-la", self.current_dir], timeout=45)
            def apply():
                self.tree.delete(*self.tree.get_children())
                if code != 0:
                    self.status_lbl.config(text=f"读取失败（code={code}），请检查 AVD 是否已开机并授权", fg=DANGER)
                    self.tree.insert("", "end", iid="__err__",
                                     text=f"（读取失败：{code}）",
                                     values=("—", "—", out[:120].replace("\n", " ")))
                    return
                rows = self._parse_ls(out, self.current_dir)
                self._files = rows
                # 先列目录、再列文件
                rows_sorted = sorted(rows, key=lambda r: (0 if r[1] else 1, r[0].lower()))
                if self.current_dir != "/":
                    self.tree.insert("", "end", iid="__up__", text=".. (上层目录)",
                                     values=("目录", "—", "—"), open=False)
                for name, is_dir, size_int, tstr, full in rows_sorted:
                    display = "📁 " + name if is_dir else "📄 " + name
                    if is_dir:
                        sz = "—"
                    else:
                        sz = self._fmt_size(size_int)
                    iid = full
                    self.tree.insert("", "end", iid=iid, text=display,
                                     values=("目录" if is_dir else "文件", sz, tstr),
                                     tags=("dir" if is_dir else "file",))
                self.status_lbl.config(text=f"{len(rows_sorted)} 项", fg=MUTED)
            self.after(0, apply)
        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _fmt_size(n):
        if n <= 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        f = float(n)
        while f >= 1024 and i < len(units) - 1:
            f /= 1024
            i += 1
        return ("%.1f %s" % (f, units[i])) if i else ("%d %s" % (n, units[i]))

    # ---------- 事件 ----------
    def _selected_row(self):
        sel = self.tree.selection()
        if not sel:
            return None, None
        iid = sel[0]
        if iid in ("__up__", "__err__"):
            return None, None
        # 在 self._files 里找对应 fullpath
        for _name, is_dir, _sz, _tm, full in self._files:
            if full == iid:
                return full, is_dir
        return None, None

    def _on_row_dblclick(self, _evt):
        full, is_dir = self._selected_row()
        if full is None:
            # 可能选中了 ".."
            sel = self.tree.selection()
            if sel and sel[0] == "__up__":
                self.cd_parent()
            return
        if is_dir:
            self.cd(full)
        else:
            self.log_fn(f"[文件浏览] 下载 {full}")
            self._pull_file(full, open_after=True)

    def _on_tree_rightclick(self, evt):
        iid = self.tree.identify_row(evt.y)
        if iid:
            self.tree.selection_set(iid)
        self.ctx_menu.tk_popup(evt.x_root, evt.y_root)

    # ---------- 下载 ----------
    def _pull_file(self, remote_path, open_after=False):
        local_name = remote_path.replace("/", "_").lstrip("_") or "remote_file"
        # 去重：同名则追加时间戳
        target = os.path.join(self.download_dir, local_name)
        base, ext = os.path.splitext(target)
        i = 1
        while os.path.exists(target):
            target = f"{base}_{i}{ext}"
            i += 1
        self.status_lbl.config(text=f"下载中：{os.path.basename(target)}", fg=WARN)

        def worker():
            code, out = self._adb(["pull", remote_path, target], timeout=120)

            def finish():
                if code == 0 and os.path.exists(target):
                    self.status_lbl.config(text=f"已保存到：{target}", fg=SUCCESS)
                    self.log_fn(f"[文件浏览] ✓ 已下载：{remote_path} → {target}")
                    if open_after:
                        try:
                            os.startfile(target)
                        except Exception as e:
                            messagebox.showwarning("已下载",
                                f"文件已下载：\n{target}\n\n无法自动打开：{e}", parent=self)
                else:
                    self.status_lbl.config(text="下载失败", fg=DANGER)
                    self.log_fn(f"[文件浏览] ✗ 下载失败 {remote_path}（{code}）：{out[:200]}")
            self.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    def _ctx_download(self):
        full, is_dir = self._selected_row()
        if full is None:
            messagebox.showinfo("提示", "请先选择要下载的文件/目录。", parent=self)
            return
        if is_dir:
            messagebox.showinfo("提示", "暂不支持目录下载，请进入目录后下载单个文件，或通过 adb pull -a 自行操作。", parent=self)
            return
        self._pull_file(full, open_after=True)

    def _open_download_dir(self):
        self.log_fn(f"[文件浏览] 打开本地下载目录：{self.download_dir}")
        try:
            os.startfile(self.download_dir)
        except Exception as e:
            messagebox.showerror("打开失败",
                f"无法打开下载目录：\n{self.download_dir}\n\n{e}", parent=self)


# ============================================================
# AVD 虚拟按键面板（电源 / 音量+ / 音量-），悬浮于 AVD 窗口之上
# ============================================================
class AdbKeyPad(tk.Toplevel):
    """always-on-top 的小工具栏，发送 adb shell input keyevent。

    特性：
     - 3 个大圆角按钮：🔌 电源（Power）/ 🔊+ 音量加 / 🔉- 音量减
     - 可拖动：在窗口空白处按住左键拖动
     - 可选择目标设备（多设备场景）
     - 可选"附着到 AVD 窗口"：通过 user32 查找 emulator 窗口并把面板贴在其右上角
     - 支持长按"电源" 2 秒（发送 long press）
    """

    KEY_POWER = 26
    KEY_VOLUME_UP = 24
    KEY_VOLUME_DOWN = 25

    def __init__(self, master=None, initial_serial=None, initial_avd=None, log_fn=None):
        super().__init__(master)
        self.title("AVD 虚拟按键")
        self.configure(bg=BG)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        try:
            self.attributes("-alpha", 0.96)
        except Exception:
            pass
        self.log_fn = log_fn or (lambda m: None)
        self.serial = initial_serial
        self.avd_name = initial_avd
        self._follow_enabled = True
        self._target_hwnd = None  # 最近一次定位到的 HWND
        self._drag = None  # (x, y)
        self._pressed_timer = None
        # 电源按钮用：True → command 里真正执行短按；长按 fire 时把它 False，release 时恢复
        self._power_short_enabled = True
        self._press_long_fired = False

        self._build_ui()
        self._refresh_targets()

        # 窗口大小
        self.update_idletasks()
        self.geometry("320x110")
        # 初始位置：屏幕右中，或跟随 AVD
        self._place_initial()
        # 绑定鼠标拖动（全窗口可拖）
        for w in (self,) + tuple(self._get_all_children(self)):
            # 只在非按钮区允许拖动？更友好：整个窗口都可拖动（按钮按下不拖）
            try:
                w.bind("<ButtonPress-1>", self._on_drag_start, add="+")
                w.bind("<B1-Motion>", self._on_drag_move, add="+")
            except Exception:
                pass
        # 按钮区域不要触发拖动：拦截按钮的 drag 由按钮自己处理
        self._attach_mode = tk.BooleanVar(value=True)
        # 定时器：跟随 AVD 窗口位置 + 刷新设备列表
        self._follow_tick()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- UI ----------
    def _build_ui(self):
        pad = 10
        root = tk.Frame(self, bg=BG, padx=pad, pady=pad)
        root.pack(fill="both", expand=True)

        top = tk.Frame(root, bg=BG)
        top.pack(fill="x", pady=(0, 8))
        tk.Label(top, text="🎯 目标：", bg=BG, fg=TEXT_SOFT, font=CN_SM).pack(side="left")
        self.target_var = tk.StringVar(value=(f"{self.avd_name} ({self.serial})"
                                              if self.avd_name and self.serial
                                              else "选择设备…"))
        self.target_menu = ttk.Combobox(top, textvariable=self.target_var, state="readonly",
                                         width=34, font=CN_SM)
        self.target_menu.pack(side="left", fill="x", expand=True, padx=(4, 6))
        self.target_menu.bind("<<ComboboxSelected>>", self._on_target_change)
        make_button(top, "🔄", self._refresh_targets, "ghost", padx=6, pady=2, radius=10).pack(side="left")

        # 按钮行
        btns = tk.Frame(root, bg=BG)
        btns.pack(fill="x")
        def _power_short():
            if self._power_short_enabled:
                self._send_key(self.KEY_POWER, long_press=False)
        self.btn_power  = make_button(btns, "🔌 电源",   _power_short,
                                      "primary", padx=14, pady=10, radius=14)
        self.btn_up     = make_button(btns, "🔊 音量 +", lambda: self._send_key(self.KEY_VOLUME_UP),
                                      "ghost",   padx=14, pady=10, radius=14)
        self.btn_down   = make_button(btns, "🔉 音量 -", lambda: self._send_key(self.KEY_VOLUME_DOWN),
                                      "ghost",   padx=14, pady=10, radius=14)
        self.btn_power.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.btn_up.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.btn_down.pack(side="left", fill="x", expand=True)
        # 电源长按：按住 1.2s 触发 --longpress；否则视为短按
        try:
            c_power = self.btn_power._c
            c_power.bind("<ButtonPress-1>",   self._on_power_press,   add="+")
            c_power.bind("<ButtonRelease-1>", self._on_power_release, add="+")
        except Exception:
            pass
        # 底部选项
        bot = tk.Frame(root, bg=BG)
        bot.pack(fill="x", pady=(8, 0))
        tk.Checkbutton(bot, text="贴靠 AVD 窗口（跟随移动）",
                       variable=self._attach_mode, bg=BG, fg=TEXT_SOFT,
                       selectcolor=CARD, activebackground=BG, activeforeground=TEXT,
                       font=CN_SM, highlightthickness=0, bd=0).pack(side="left")
        self.status_lbl = tk.Label(bot, text="就绪", bg=BG, fg=MUTED, font=CN_SM, anchor="e")
        self.status_lbl.pack(side="right")

    @staticmethod
    def _get_all_children(widget, out=None):
        if out is None:
            out = []
        for c in widget.winfo_children():
            out.append(c)
            AdbKeyPad._get_all_children(c, out)
        return out

    # ---------- 目标设备 ----------
    def _refresh_targets(self, _=None):
        """刷新设备下拉列表"""
        try:
            devs = running_devices()
        except Exception:
            devs = []
        values = []
        self._dev_mapping = {}  # display -> serial
        if not devs:
            values.append("（当前无在线设备，请先启动 AVD）")
            self.target_menu["values"] = values
            self.target_var.set(values[0])
            self.status_lbl.config(text="无在线设备", fg=WARN)
            return
        # 尝试把 serial 映射到 AVD 名
        rmap = {s: n for n, s in (getattr(self.master, "_avd_serials", None) or {}).items()}
        for s, st in devs:
            name = rmap.get(s)
            label = (f"{name}（{s} · {st}）") if name else f"{s} · {st}"
            values.append(label)
            self._dev_mapping[label] = s
        self.target_menu["values"] = values
        # 如果当前 serial 在列表内则选中它
        chosen = None
        if self.serial:
            for lbl, s in self._dev_mapping.items():
                if s == self.serial:
                    chosen = lbl
                    break
        if chosen is None and values:
            chosen = values[0]
            self.serial = self._dev_mapping.get(chosen)
            self.avd_name = self._avd_name_for_serial(self.serial)
        self.target_var.set(chosen or "选择设备…")
        self.status_lbl.config(text=f"已连接：{self.serial or '未选择'}",
                               fg=(SUCCESS if self.serial else WARN))

    def _avd_name_for_serial(self, serial):
        rmap = {s: n for n, s in (getattr(self.master, "_avd_serials", None) or {}).items()}
        return rmap.get(serial)

    def _on_target_change(self, _evt):
        lbl = self.target_var.get()
        s = self._dev_mapping.get(lbl)
        if s:
            self.serial = s
            self.avd_name = self._avd_name_for_serial(s)
            self.status_lbl.config(text=f"已切换：{s}", fg=SUCCESS)
            self.log_fn(f"[虚拟按键] 切换目标：{self.avd_name or s}（{s}）")

    # ---------- 按键发送 ----------
    def _adb(self, args, timeout=12):
        if not os.path.exists(ADB):
            return -1, "adb 未找到"
        full = [ADB, "-s", self.serial] + list(args) if self.serial else [ADB] + list(args)
        try:
            proc = subprocess.run(full, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  timeout=timeout,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return proc.returncode, proc.stdout.decode("utf-8", errors="replace")
        except Exception as e:
            return -1, f"[错误] {e}"

    def _send_key(self, keycode, long_press=False, dur_ms=1500):
        if not self.serial:
            self.status_lbl.config(text="请先选择目标设备", fg=WARN)
            return
        self.status_lbl.config(text=f"发送 key {keycode}{' (长按)' if long_press else ''}…", fg=WARN)
        args = ["shell", "input", "keyevent", str(keycode)]
        if long_press:
            # long press 用组合命令 --longpress
            args = ["shell", "input", "keyevent", "--longpress", str(keycode)]

        def worker():
            code, out = self._adb(args, timeout=15)
            def finish():
                if code == 0:
                    self.status_lbl.config(text=f"✓ 发送 key {keycode}", fg=SUCCESS)
                    self.log_fn(f"[虚拟按键] 发送 key {keycode} 到 {self.serial}")
                else:
                    self.status_lbl.config(text="发送失败", fg=DANGER)
                    self.log_fn(f"[虚拟按键] ✗ key {keycode} 失败（{code}）：{out[:180]}")
            self.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    # 电源长按
    def _on_power_press(self, e):
        # 延迟 1.2s 后标记长按
        if self._pressed_timer is not None:
            try: self.after_cancel(self._pressed_timer)
            except Exception: pass
        self._press_long_fired = False
        self._pressed_timer = self.after(1200, self._fire_long)

    def _fire_long(self):
        self._press_long_fired = True
        # 先禁用一次短按（接着到来的 release 上的 command 不会再发）
        self._power_short_enabled = False
        self._send_key(self.KEY_POWER, long_press=True)

    def _on_power_release(self, e):
        if self._pressed_timer is not None:
            try: self.after_cancel(self._pressed_timer)
            except Exception: pass
            self._pressed_timer = None
        # 若本次长按已 fire，则在 80ms 后再解禁短按（防止 release 上的 command 立即触发）
        if self._press_long_fired:
            self._press_long_fired = False
            self.after(80, self._reenable_power_short)
        else:
            # 正常短按：保持 enabled，交给按钮自带 command 去发送
            self._power_short_enabled = True

    def _reenable_power_short(self):
        self._power_short_enabled = True

    # ---------- 拖动 ----------
    def _on_drag_start(self, e):
        # 如果点击目标是按钮（Canvas），不要拖动，以免影响按钮点击
        w = e.widget
        if isinstance(w, tk.Canvas):
            # 按钮自己的 canvas —— 不拖动
            return
        self._drag = (e.x_root - self.winfo_x(), e.y_root - self.winfo_y())

    def _on_drag_move(self, e):
        if self._drag is None:
            return
        dx, dy = self._drag
        self.geometry(f"+{e.x_root - dx}+{e.y_root - dy}")
        # 用户手动拖动了一次 → 暂时关闭 attach，避免又被拉回去
        self._attach_mode.set(False)

    # ---------- 附着窗口（user32 查找 HWND 并跟随） ----------
    def _place_initial(self):
        try:
            # 放右下角 1/4 处，或贴近 AVD 窗口
            hwnd = self._find_emulator_hwnd()
            if hwnd and self._attach_mode.get():
                self._attach_to_hwnd(hwnd)
                return
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            self.geometry(f"+{sw - 360}+{sh // 3}")
        except Exception:
            pass

    def _find_emulator_hwnd(self):
        """Windows 下查找目标 AVD 对应的 emulator 主窗口句柄。

        优先匹配 "Android Emulator - <avd_name>"；否则匹配任意包含 "Emulator" 且可见的窗口。
        """
        if os.name != "nt":
            return None
        try:
            import ctypes
            from ctypes import wintypes
        except Exception:
            return None
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL,
                                             wintypes.HWND, wintypes.LPARAM)
        IsWindowVisible = user32.IsWindowVisible
        IsWindowVisible.restype = wintypes.BOOL
        GetWindowTextLengthW = user32.GetWindowTextLengthW
        GetWindowTextLengthW.restype = ctypes.c_int
        GetWindowTextW = user32.GetWindowTextW
        GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        GetWindowTextW.restype = ctypes.c_int
        candidates = []
        def cb(hwnd, _lparam):
            if not IsWindowVisible(hwnd):
                return True
            length = GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            if self.avd_name and f"Android Emulator - {self.avd_name}" in title:
                candidates.insert(0, hwnd)
            elif "Android Emulator" in title or "Emulator" in title:
                candidates.append(hwnd)
            return True
        user32.EnumWindows(EnumWindowsProc(cb), 0)
        # 还可以根据 emulator-<port> 里的 5554 → "5554" 在标题里匹配
        if not candidates and isinstance(self.serial, str) and "emulator-" in self.serial:
            try:
                port = self.serial.split("-", 1)[1]
            except Exception:
                port = None
            if port:
                def cb2(hwnd, _lp):
                    if not IsWindowVisible(hwnd):
                        return True
                    length = GetWindowTextLengthW(hwnd)
                    if length <= 0:
                        return True
                    buf = ctypes.create_unicode_buffer(length + 1)
                    GetWindowTextW(hwnd, buf, length + 1)
                    if port in buf.value:
                        candidates.append(hwnd)
                    return True
                user32.EnumWindows(EnumWindowsProc(cb2), 0)
        return candidates[0] if candidates else None

    def _get_hwnd_rect(self, hwnd):
        try:
            import ctypes
            from ctypes import wintypes
        except Exception:
            return None
        class RECT(ctypes.Structure):
            _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                        ("right", wintypes.LONG), ("bottom", wintypes.LONG)]
        r = RECT()
        try:
            ok = ctypes.WinDLL("user32", use_last_error=True).GetWindowRect(
                wintypes.HWND(hwnd), ctypes.byref(r))
        except Exception:
            return None
        if not ok:
            return None
        return (r.left, r.top, r.right, r.bottom)

    def _attach_to_hwnd(self, hwnd):
        rect = self._get_hwnd_rect(hwnd)
        if not rect:
            return
        left, top, right, bottom = rect
        # 把按键面板放到 emulator 窗口 右上角外 20px，竖直居中于上半
        w = max(self.winfo_width(), 320)
        h = max(self.winfo_height(), 110)
        # 放在右上角右边
        new_x = right + 12
        new_y = top + 40
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        # 超出屏幕右边界 → 改为贴在 emulator 顶部上方
        if new_x + w > sw - 20:
            new_x = right - w
            new_y = top - h - 16
            if new_y < 0:
                new_y = top + 16
        self.geometry(f"{w}x{h}+{new_x}+{new_y}")

    def _follow_tick(self):
        try:
            if self._attach_mode.get():
                hwnd = self._find_emulator_hwnd()
                if hwnd:
                    self._target_hwnd = hwnd
                    try:
                        self._attach_to_hwnd(hwnd)
                    except Exception:
                        pass
        except Exception:
            pass
        # 每 500ms 刷新跟随，每 10s 刷新设备下拉
        if not getattr(self, "_tick_counter", None):
            self._tick_counter = 0
        self._tick_counter = (self._tick_counter + 1) % 20
        if self._tick_counter == 0:
            self._refresh_targets()
        if getattr(self, "_alive", True):
            self.after(500, self._follow_tick)

    def _on_close(self):
        self._alive = False
        self.destroy()


if __name__ == "__main__":
    app = LauncherApp()
    app.mainloop()
