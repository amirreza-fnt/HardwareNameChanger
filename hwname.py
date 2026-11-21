# -*- coding: utf-8 -*-
"""Fun hardware-name changer: changes the GPU/CPU names Windows shows (cosmetic only)."""
import ctypes, json, os, shutil, subprocess, sys, winreg
import tkinter as tk
from tkinter import messagebox

APP = "HardwareNameChanger"
DATA_DIR = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), APP)
BACKUP = os.path.join(DATA_DIR, "backup.json")
TASK = APP + "_CPU"
GPU_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
CPU_ROOT = r"HARDWARE\DESCRIPTION\System\CentralProcessor"
NOWIN = 0x08000000  # CREATE_NO_WINDOW


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def subkeys(path):
    out = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            i = 0
            while True:
                try:
                    out.append(winreg.EnumKey(k, i)); i += 1
                except OSError:
                    break
    except OSError:
        pass
    return out


def read(path, name):
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def write(path, name, value):
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)


def gpu_keys():
    return [GPU_CLASS + "\\" + s for s in subkeys(GPU_CLASS)
            if s.isdigit() and read(GPU_CLASS + "\\" + s, "DriverDesc") is not None]


def cpu_keys():
    return [CPU_ROOT + "\\" + s for s in subkeys(CPU_ROOT)
            if read(CPU_ROOT + "\\" + s, "ProcessorNameString") is not None]


def hide_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
    subprocess.run(["attrib", "+h", "+s", DATA_DIR], capture_output=True, creationflags=NOWIN)


ENUM = r"SYSTEM\CurrentControlSet\Enum"


def read_raw(path, name):
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            return winreg.QueryValueEx(k, name)
    except OSError:
        return None


def write_raw(path, name, value, typ):
    typ &= 0xFFFFFFFF
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, typ, value)


def delete_value(path, name):
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
    except OSError:
        pass


def gpu_devices():
    """Enum keys of display devices (Device Manager / Settings read FriendlyName from here)."""
    out = []
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-PnpDevice -Class Display | % InstanceId"],
                           capture_output=True, text=True, creationflags=NOWIN)
        for line in r.stdout.splitlines():
            if line.strip():
                out.append(ENUM + "\\" + line.strip())
    except Exception:
        pass
    return out


ADAPTER_VALUES = ("HardwareInformation.AdapterString",)


def current_names():
    g = gpu_keys(); c = cpu_keys()
    return (read(g[0], "DriverDesc") if g else ""), (read(c[0], "ProcessorNameString") if c else "")


def make_backup():
    hide_dir()
    data = None
    if os.path.exists(BACKUP):
        with open(BACKUP, encoding="utf-8") as f:
            data = json.load(f)
        if "gpu_extra" in data:
            if "gpu_desc" not in data:
                data["gpu_desc"] = {k: read(k, "DeviceDesc") for k in gpu_devices()}
                with open(BACKUP, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            return  # keep the very first original values
    if data is None:
        data = {"gpu": {k: read(k, "DriverDesc") for k in gpu_keys()},
                "cpu": {k: read(k, "ProcessorNameString") for k in cpu_keys()}}
    extra = {}
    for k in gpu_keys():
        for v in ADAPTER_VALUES:
            raw = read_raw(k, v)
            extra[k + "|" + v] = [raw[0].hex(), raw[1]] if raw and isinstance(raw[0], bytes) else None
    for k in gpu_devices():
        raw = read_raw(k, "FriendlyName")
        extra[k + "|FriendlyName"] = raw[0] if raw else None
    data["gpu_extra"] = extra
    data["gpu_desc"] = {k: read(k, "DeviceDesc") for k in gpu_devices()}
    with open(BACKUP, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # extra .reg backup on Desktop, like the original batch file
    desk = os.path.join(DATA_DIR, "gpu_backup.reg")
    if not os.path.exists(desk):
        subprocess.run(["reg", "export", "HKLM\\" + GPU_CLASS, desk, "/y"],
                       capture_output=True, creationflags=NOWIN)


def set_cpu(name):
    for k in cpu_keys():
        write(k, "ProcessorNameString", name)


DRIVER_PROPS = r"Properties\{a8b865dd-2e3d-4094-ad97-e593a70c75d6}\0004"  # DEVPKEY_Device_DriverDesc
STR_PROP_TYPE = 0xFFFF0012  # registry type PnP uses for DEVPROP_TYPE_STRING
GPU_PROPS_BACKUP = os.path.join(DATA_DIR, "gpu_props.json")
CPU_FILE = os.path.join(DATA_DIR, "cpu_name.txt")
GPU_FILE = os.path.join(DATA_DIR, "gpu_name.txt")
EXE = os.path.join(DATA_DIR, APP + ".exe")
ONCE_TASK = APP + "_Once"
LANG_FILE = os.path.join(DATA_DIR, "lang.txt")


class NoBackupError(RuntimeError):
    """Restore was requested but no first-run backup exists."""



def ensure_exe():
    hide_dir()
    if getattr(sys, "frozen", False) and os.path.abspath(sys.executable).lower() != EXE.lower():
        shutil.copy2(sys.executable, EXE)


def task_xml(args, boot=True):
    triggers = ("<BootTrigger><Enabled>true</Enabled><Delay>PT5S</Delay></BootTrigger>"
                "<LogonTrigger><Enabled>true</Enabled></LogonTrigger>") if boot else \
               "<TimeTrigger><StartBoundary>2000-01-01T00:00:00</StartBoundary><Enabled>true</Enabled></TimeTrigger>"
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>{triggers}</Triggers>
  <Principals><Principal id="Author"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
    <Hidden>true</Hidden>
    <StartWhenAvailable>true</StartWhenAvailable>
  </Settings>
  <Actions Context="Author"><Exec><Command>{EXE}</Command><Arguments>{args}</Arguments></Exec></Actions>
</Task>"""


def create_task(name, xml):
    p = os.path.join(DATA_DIR, name + ".xml")
    with open(p, "w", encoding="utf-16") as f:
        f.write(xml)
    subprocess.run(["schtasks", "/Create", "/F", "/TN", name, "/XML", p], capture_output=True, creationflags=NOWIN)
    os.remove(p)


def delete_task(name):
    subprocess.run(["schtasks", "/Delete", "/F", "/TN", name], capture_output=True, creationflags=NOWIN)


def run_as_system_now():
    """Run '--system' once as SYSTEM (only SYSTEM may write the protected PnP property) and wait."""
    import time
    marker = os.path.join(DATA_DIR, "done.txt")
    try: os.remove(marker)
    except OSError: pass
    create_task(ONCE_TASK, task_xml("--system", boot=False))
    subprocess.run(["schtasks", "/Run", "/TN", ONCE_TASK], capture_output=True, creationflags=NOWIN)
    for _ in range(60):
        if os.path.exists(marker):
            break
        time.sleep(0.25)
    delete_task(ONCE_TASK)
    try: os.remove(marker)
    except OSError: pass


def refresh_boot_task():
    delete_task(TASK)
    if os.path.exists(CPU_FILE) or os.path.exists(GPU_FILE) or os.path.exists(VRAM_FILE):
        create_task(TASK, task_xml("--system"))


VRAM_FILE = os.path.join(DATA_DIR, "vram.txt")
EXTRA_BACKUP = os.path.join(DATA_DIR, "gpu_extra2.json")
DX_ROOT = r"SOFTWARE\Microsoft\DirectX"


def dx_keys():
    return [DX_ROOT + "\\" + s for s in subkeys(DX_ROOT)
            if (read(DX_ROOT + "\\" + s, "Description") or "") and
            "Basic Render" not in (read(DX_ROOT + "\\" + s, "Description") or "") and
            read(DX_ROOT + "\\" + s, "DedicatedVideoMemory") is not None]


def extra_targets():
    t = []
    for k in gpu_keys():
        for v in ("HardwareInformation.AdapterString", "HardwareInformation.ChipType",
                  "HardwareInformation.MemorySize", "HardwareInformation.qwMemorySize"):
            t.append((k, v))
    for k in dx_keys():
        t += [(k, "Description"), (k, "DedicatedVideoMemory")]
    return t


def raw_to_json(raw):
    if raw is None:
        return None
    val, typ = raw
    if isinstance(val, str):
        return ["s", val, typ]
    if isinstance(val, int):
        return ["i", val, typ]
    return ["b", bytes(val).hex(), typ]


def json_to_raw(j):
    kind, val, typ = j
    return (bytes.fromhex(val) if kind == "b" else val), typ


def system_extras():
    gpu = vram = None
    if os.path.exists(GPU_FILE):
        with open(GPU_FILE, encoding="utf-8") as fh: gpu = fh.read().strip()
    if os.path.exists(VRAM_FILE):
        with open(VRAM_FILE, encoding="utf-8") as fh: vram = int(fh.read().strip())
    if gpu is None and vram is None:
        if os.path.exists(EXTRA_BACKUP):
            with open(EXTRA_BACKUP, encoding="utf-8") as f: bk = json.load(f)
            for key, j in bk.items():
                path, name = key.rsplit("|", 1)
                try:
                    if j is None: continue
                    val, typ = json_to_raw(j); write_raw(path, name, val, typ)
                except OSError: pass
            os.remove(EXTRA_BACKUP)
        return
    if not os.path.exists(EXTRA_BACKUP):
        bk = {f"{k}|{v}": raw_to_json(read_raw(k, v)) for k, v in extra_targets()}
        with open(EXTRA_BACKUP, "w", encoding="utf-8") as f: json.dump(bk, f)
    for k, v in extra_targets():
        cur = read_raw(k, v)
        if cur is None:
            continue
        try:
            if gpu and v in ("HardwareInformation.AdapterString",):
                write_raw(k, v, (gpu + "\0").encode("utf-16-le"), winreg.REG_BINARY)
            elif gpu and v == "Description":
                write_raw(k, v, gpu, winreg.REG_SZ)
            elif vram and v == "HardwareInformation.MemorySize":
                write_raw(k, v, min(vram, 0xFFF00000).to_bytes(4, "little"), cur[1])
            elif vram and v in ("HardwareInformation.qwMemorySize", "DedicatedVideoMemory"):
                if cur[1] == winreg.REG_QWORD:
                    write_raw(k, v, vram, winreg.REG_QWORD)
                elif cur[1] == winreg.REG_DWORD:
                    write_raw(k, v, min(vram, 0xFFFFFFFF), winreg.REG_DWORD)
                else:
                    write_raw(k, v, vram.to_bytes(8, "little"), cur[1])
        except OSError:
            pass


def system_mode():
    """Runs as SYSTEM: CPU name (volatile key) + protected GPU driver description."""
    try:
        if os.path.exists(CPU_FILE):
            with open(CPU_FILE, encoding="utf-8") as fh:
                set_cpu(fh.read().strip())
        props = [d + "\\" + DRIVER_PROPS for d in gpu_devices()]
        if os.path.exists(GPU_FILE):
            with open(GPU_FILE, encoding="utf-8") as fh:
                name = fh.read().strip()
            if not os.path.exists(GPU_PROPS_BACKUP):
                bk = {}
                for p in props:
                    raw = read_raw(p, "")
                    if raw:
                        bk[p] = [bytes(raw[0]).hex() if not isinstance(raw[0], str) else raw[0].encode("utf-16-le").hex(), raw[1]]
                with open(GPU_PROPS_BACKUP, "w", encoding="utf-8") as f:
                    json.dump(bk, f)
            for p in props:
                if read_raw(p, "") is not None:
                    write_raw(p, "", (name + "\0").encode("utf-16-le"), STR_PROP_TYPE)
        elif os.path.exists(GPU_PROPS_BACKUP):
            with open(GPU_PROPS_BACKUP, encoding="utf-8") as f:
                bk = json.load(f)
            for p, (hx, typ) in bk.items():
                try: write_raw(p, "", bytes.fromhex(hx), typ)
                except OSError: pass
            os.remove(GPU_PROPS_BACKUP)
        system_extras()
    finally:
        open(os.path.join(DATA_DIR, "done.txt"), "w").close()


def apply(gpu, cpu, persist, vram=None):
    make_backup()
    ensure_exe()
    if vram:
        with open(VRAM_FILE, "w", encoding="utf-8") as f:
            f.write(str(vram))
    if gpu:
        for k in gpu_keys():
            write(k, "DriverDesc", gpu)
            for v in ADAPTER_VALUES:
                if read_raw(k, v):
                    write_raw(k, v, (gpu + "\0").encode("utf-16-le"), winreg.REG_BINARY)
        for k in gpu_devices():
            for v in ("FriendlyName", "DeviceDesc"):
                try: write(k, v, gpu)
                except OSError: pass
        with open(GPU_FILE, "w", encoding="utf-8") as f:
            f.write(gpu)
    if cpu:
        set_cpu(cpu)
        if persist:
            with open(CPU_FILE, "w", encoding="utf-8") as f:
                f.write(cpu)
        else:
            try: os.remove(CPU_FILE)
            except OSError: pass
    if gpu or vram:
        run_as_system_now()
    refresh_boot_task()


def restore():
    if not os.path.exists(BACKUP):
        raise NoBackupError()
    with open(BACKUP, encoding="utf-8") as f:
        data = json.load(f)
    for k, v in data.get("gpu", {}).items():
        if v is not None: write(k, "DriverDesc", v)
    for key, v in data.get("gpu_extra", {}).items():
        path, name = key.rsplit("|", 1)
        try:
            if v is None:
                delete_value(path, name)
            elif isinstance(v, list):
                write_raw(path, name, bytes.fromhex(v[0]), v[1])
            else:
                write(path, name, v)
        except OSError:
            pass
    for k, v in data.get("gpu_desc", {}).items():
        if v:
            try: write(k, "DeviceDesc", v)
            except OSError: pass
    for k, v in data.get("cpu", {}).items():
        if v is not None:
            try: write(k, "ProcessorNameString", v)
            except OSError: pass
    for p in (CPU_FILE, GPU_FILE, VRAM_FILE):
        try: os.remove(p)
        except OSError: pass
    ensure_exe()
    if os.path.exists(GPU_PROPS_BACKUP) or os.path.exists(EXTRA_BACKUP):
        run_as_system_now()
    refresh_boot_task()
    os.remove(BACKUP)



# --- UI language -----------------------------------------------------------

PRESETS = {
    "GPU": {
        "nvidia_50": ["NVIDIA GeForce RTX 5090", "NVIDIA GeForce RTX 5080", "NVIDIA GeForce RTX 5070 Ti",
                      "NVIDIA GeForce RTX 5070", "NVIDIA GeForce RTX 5060 Ti", "NVIDIA GeForce RTX 5060"],
        "nvidia_40": ["NVIDIA GeForce RTX 4090", "NVIDIA GeForce RTX 4080 SUPER", "NVIDIA GeForce RTX 4080",
                      "NVIDIA GeForce RTX 4070 Ti SUPER", "NVIDIA GeForce RTX 4070 SUPER", "NVIDIA GeForce RTX 4070",
                      "NVIDIA GeForce RTX 4060 Ti", "NVIDIA GeForce RTX 4060"],
        "nvidia_30": ["NVIDIA GeForce RTX 3090 Ti", "NVIDIA GeForce RTX 3090", "NVIDIA GeForce RTX 3080 Ti",
                      "NVIDIA GeForce RTX 3080", "NVIDIA GeForce RTX 3070 Ti", "NVIDIA GeForce RTX 3070",
                      "NVIDIA GeForce RTX 3060 Ti", "NVIDIA GeForce RTX 3060"],
        "nvidia_other": ["NVIDIA GeForce GTX 1080 Ti", "NVIDIA GeForce GTX 1660 SUPER",
                         "NVIDIA GeForce GTX 1050 Ti", "NVIDIA RTX 6000 Ada Generation",
                         "NVIDIA H100 80GB HBM3", "NVIDIA TITAN RTX"],
        "amd": ["AMD Radeon RX 9070 XT", "AMD Radeon RX 9070", "AMD Radeon RX 7900 XTX",
                "AMD Radeon RX 7900 XT", "AMD Radeon RX 7800 XT", "AMD Radeon RX 7700 XT",
                "AMD Radeon RX 7600", "AMD Radeon RX 6950 XT", "AMD Radeon RX 6800 XT", "AMD Radeon RX 580"],
        "intel": ["Intel(R) Arc(TM) B580 Graphics", "Intel(R) Arc(TM) A770 Graphics",
                  "Intel(R) Arc(TM) A750 Graphics", "Intel(R) UHD Graphics 630"],
        "fun": ["NVIDIA GeForce RTX 9090 Ti Ultra", "کارت گرافیک ناسا", "Potato Graphics 2000",
                "سیب‌زمینی با فن", "NASA Quantum GPU", "GeForce RTX ∞", "S3 Trio64 (1995)"],
    },
    "CPU": {
        "intel_ultra": ["Intel(R) Core(TM) Ultra 9 285K", "Intel(R) Core(TM) Ultra 7 265K",
                        "Intel(R) Core(TM) Ultra 5 245K"],
        "intel_core": ["Intel(R) Core(TM) i9-14900KS", "Intel(R) Core(TM) i9-14900K",
                       "Intel(R) Core(TM) i7-14700K", "Intel(R) Core(TM) i5-14600K",
                       "Intel(R) Core(TM) i9-13900K", "Intel(R) Core(TM) i5-13400F"],
        "intel_xeon": ["Intel(R) Xeon(R) Platinum 8490H", "Intel(R) Xeon(R) w9-3495X", "Intel(R) Xeon(R) Gold 6448Y"],
        "amd_ryzen": ["AMD Ryzen 9 9950X3D 16-Core Processor", "AMD Ryzen 9 9950X 16-Core Processor",
                      "AMD Ryzen 7 9800X3D 8-Core Processor", "AMD Ryzen 9 7950X3D 16-Core Processor",
                      "AMD Ryzen 7 7800X3D 8-Core Processor", "AMD Ryzen 5 7600X 6-Core Processor",
                      "AMD Ryzen 5 5600X 6-Core Processor"],
        "amd_tr": ["AMD Ryzen Threadripper PRO 7995WX 96-Cores",
                   "AMD Ryzen Threadripper 7980X 64-Cores", "AMD EPYC 9654 96-Core Processor"],
        "apple": ["Apple M4 Max", "Apple M3 Ultra", "Qualcomm Snapdragon X Elite"],
        "fun": ["Intel Core i15-99999K @ 99 GHz", "پردازنده‌ی کوانتومی ناسا", "Pentium 4 (با عشق)",
                "AMD Ryzen 99 9999X 1024-Core", "Potato Processor 1.0 GHz", "مغز متفکر 3000"],
    },
}

VRAM_GB = ("2 GB", "4 GB", "6 GB", "8 GB", "10 GB", "12 GB", "16 GB", "20 GB", "24 GB", "32 GB", "48 GB", "80 GB")

STRINGS = {
    "en": {
        "title": "Hardware Name Changer",
        "header": "Hardware Name Changer",
        "subtitle": "Rename the CPU and GPU names Windows shows — cosmetic only",
        "tab_gpu": "  Graphics Card  ",
        "tab_cpu": "  Processor  ",
        "current_label": "Current name:",
        "chosen": "Selected or custom name",
        "vram": "Graphics memory",
        "vram_none": "No change",
        "persist": "Keep the CPU name after restart",
        "apply": "Apply changes",
        "restore": "Restore to original",
        "lang": "Language",
        "invalid_num_title": "Invalid number",
        "invalid_num": "Enter memory in GB, for example 16.",
        "nothing_title": "Nothing selected",
        "nothing": "Pick a name from the list, or type your own.",
        "done_title": "Done",
        "done": "Change applied. Restart once to see the GPU name everywhere.",
        "restored_title": "Restored",
        "restored": "Everything was restored. Restart once for the GPU name.",
        "error": "Error",
        "no_backup": "No backup found — nothing has been changed yet.",
        "preview_title": "Preview mode",
        "preview_apply": "Preview mode: changes are not applied.",
        "preview_restore": "Preview mode: restore is disabled.",
        "status_gpu": "GPU",
        "status_cpu": "CPU",
        "cat": {
            "GPU": {
                "nvidia_50": "NVIDIA RTX 50",
                "nvidia_40": "NVIDIA RTX 40",
                "nvidia_30": "NVIDIA RTX 30",
                "nvidia_other": "NVIDIA GTX / Workstation",
                "amd": "AMD Radeon",
                "intel": "Intel Arc",
                "fun": "Fun 😄",
            },
            "CPU": {
                "intel_ultra": "Intel Core Ultra",
                "intel_core": "Intel Core 14th / 13th",
                "intel_xeon": "Intel Xeon",
                "amd_ryzen": "AMD Ryzen",
                "amd_tr": "AMD Threadripper / EPYC",
                "apple": "Apple / Other",
                "fun": "Fun 😄",
            },
        },
    },
    "fa": {
        "title": "تغییر اسم سخت‌افزار",
        "header": "تغییر اسم سخت‌افزار",
        "subtitle": "اسم نمایشی پردازنده و کارت گرافیک ویندوز را عوض کنید — فقط ظاهری",
        "tab_gpu": "  کارت گرافیک  ",
        "tab_cpu": "  پردازنده  ",
        "current_label": "اسم فعلی:",
        "chosen": "اسم انتخاب‌شده یا دلخواه",
        "vram": "حافظه کارت گرافیک",
        "vram_none": "بدون تغییر",
        "persist": "اسم CPU بعد از ری‌استارت هم بماند",
        "apply": "اعمال تغییر",
        "restore": "برگشت به حالت اول",
        "lang": "زبان",
        "invalid_num_title": "عدد نامعتبر",
        "invalid_num": "حافظه را به گیگ وارد کنید، مثلاً ۱۶.",
        "nothing_title": "هیچی انتخاب نشده",
        "nothing": "یک اسم از لیست انتخاب کنید یا خودتان بنویسید.",
        "done_title": "انجام شد",
        "done": "تغییر اعمال شد. برای دیدن اسم GPU یک‌بار ری‌استارت کنید.",
        "restored_title": "برگشت",
        "restored": "همه چیز به حالت اول برگشت. برای GPU یک‌بار ری‌استارت کنید.",
        "error": "خطا",
        "no_backup": "بکاپی پیدا نشد؛ احتمالاً هنوز چیزی تغییر نکرده.",
        "preview_title": "حالت پیش‌نمایش",
        "preview_apply": "حالت پیش‌نمایش: تغییری اعمال نمی‌شود.",
        "preview_restore": "حالت پیش‌نمایش: بازگشت غیرفعال است.",
        "status_gpu": "کارت گرافیک",
        "status_cpu": "پردازنده",
        "cat": {
            "GPU": {
                "nvidia_50": "NVIDIA RTX 50",
                "nvidia_40": "NVIDIA RTX 40",
                "nvidia_30": "NVIDIA RTX 30",
                "nvidia_other": "NVIDIA GTX / Workstation",
                "amd": "AMD Radeon",
                "intel": "Intel Arc",
                "fun": "شوخی 😄",
            },
            "CPU": {
                "intel_ultra": "Intel Core Ultra",
                "intel_core": "Intel Core — نسل ۱۳ و ۱۴",
                "intel_xeon": "Intel Xeon",
                "amd_ryzen": "AMD Ryzen",
                "amd_tr": "AMD Threadripper / EPYC",
                "apple": "Apple / دیگر",
                "fun": "شوخی 😄",
            },
        },
    },
}

C = {
    "bg": "#10131A",
    "header": "#0B0D12",
    "card": "#1A1F2B",
    "border": "#2C3344",
    "text": "#F2F4F8",
    "muted": "#9AA3B5",
    "accent": "#3EE0B7",
    "accent_hover": "#62F0CB",
    "accent_dim": "#15352F",
    "accent_text": "#06201A",
    "danger": "#F07178",
    "danger_bg": "#2A1618",
    "danger_hover": "#3A1C1F",
    "input": "#12161F",
    "tree": "#12161F",
    "row_odd": "#191E2A",
    "row_even": "#12161F",
    "status": "#0B0D12",
}


def windows_ui_lang():
    try:
        lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        if (lcid & 0x3FF) == 0x29:
            return "fa"
    except Exception:
        pass
    return "en"


def load_lang():
    try:
        if os.path.exists(LANG_FILE):
            val = open(LANG_FILE, encoding="utf-8").read().strip().lower()
            if val in ("fa", "en"):
                return val
    except Exception:
        pass
    return windows_ui_lang()


def save_lang(lang):
    try:
        hide_dir()
        with open(LANG_FILE, "w", encoding="utf-8") as f:
            f.write(lang)
    except Exception:
        pass


def set_dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _rounded(canvas, x1, y1, x2, y2, r, fill, outline=None, width=1):
    outline = fill if outline is None else outline
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    canvas.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90,
                      style="pieslice", fill=fill, outline=fill)
    canvas.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90,
                      style="pieslice", fill=fill, outline=fill)
    canvas.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90,
                      style="pieslice", fill=fill, outline=fill)
    canvas.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90,
                      style="pieslice", fill=fill, outline=fill)
    canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=fill)
    canvas.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=fill)
    if outline != fill:
        canvas.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90,
                          style="arc", outline=outline, width=width)
        canvas.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90,
                          style="arc", outline=outline, width=width)
        canvas.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90,
                          style="arc", outline=outline, width=width)
        canvas.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90,
                          style="arc", outline=outline, width=width)
        canvas.create_line(x1 + r, y1, x2 - r, y1, fill=outline, width=width)
        canvas.create_line(x1 + r, y2, x2 - r, y2, fill=outline, width=width)
        canvas.create_line(x1, y1 + r, x1, y2 - r, fill=outline, width=width)
        canvas.create_line(x2, y1 + r, x2, y2 - r, fill=outline, width=width)


class PillButton(tk.Canvas):
    def __init__(self, master, text, command, kind="primary", width=220, height=42, font=None):
        super().__init__(master, width=width, height=height, highlightthickness=0, bd=0,
                         cursor="hand2")
        self.command = command
        self.kind = kind
        self._text = text
        self._font = font
        self._bw, self._bh = width, height
        self._hover = False
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonRelease-1>", self._click)
        self.draw()

    def set_text(self, text):
        self._text = text
        self.draw()

    def _parent_bg(self):
        try:
            return self.master.cget("background")
        except tk.TclError:
            return C["bg"]

    def draw(self):
        self.delete("all")
        self.configure(bg=self._parent_bg())
        if self.kind == "primary":
            fill = C["accent_hover"] if self._hover else C["accent"]
            fg, outline = C["accent_text"], fill
        else:
            fill = C["danger_hover"] if self._hover else C["danger_bg"]
            fg, outline = C["danger"], C["danger"]
        _rounded(self, 1, 1, self._bw - 2, self._bh - 2, self._bh // 2, fill, outline, 1)
        self.create_text(self._bw // 2, self._bh // 2, text=self._text, fill=fg, font=self._font)

    def _enter(self, _):
        self._hover = True
        self.draw()

    def _leave(self, _):
        self._hover = False
        self.draw()

    def _click(self, _):
        if self.command:
            self.command()


class LangSwitch(tk.Canvas):
    def __init__(self, master, lang, on_change, font=None, width=200, height=34):
        super().__init__(master, width=width, height=height, highlightthickness=0, bd=0, cursor="hand2")
        self._lang = lang
        self._on_change = on_change
        self._font = font
        self._bw, self._bh = width, height
        self.bind("<ButtonRelease-1>", self._click)
        self.draw()

    def set_lang(self, lang):
        self._lang = lang
        self.draw()

    def _parent_bg(self):
        try:
            return self.master.cget("background")
        except tk.TclError:
            return C["header"]

    def draw(self):
        self.delete("all")
        self.configure(bg=self._parent_bg())
        w, h = self._bw, self._bh
        _rounded(self, 0, 0, w - 1, h - 1, h // 2, C["input"], C["border"], 1)
        mid = w // 2
        for i, (code, label) in enumerate((("fa", "فارسی"), ("en", "English"))):
            x1, x2 = (1, mid) if i == 0 else (mid, w - 2)
            active = self._lang == code
            if active:
                _rounded(self, x1 + 2, 3, x2 - 2, h - 4, (h - 7) // 2, C["accent"], C["accent"], 1)
            color = C["accent_text"] if active else C["muted"]
            self.create_text((x1 + x2) / 2, h / 2, text=label, fill=color, font=self._font)

    def _click(self, ev):
        new = "fa" if ev.x < self._bw / 2 else "en"
        if new != self._lang and self._on_change:
            self._on_change(new)



class FancyCheck(tk.Frame):
    def __init__(self, master, text, variable, font, is_rtl=False, command=None, bg=None):
        bg = bg or C["card"]
        super().__init__(master, bg=bg)
        self.variable = variable
        self.command = command
        self.box = tk.Canvas(self, width=22, height=22, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.lbl = tk.Label(self, text=text, bg=bg, fg=C["text"], font=font, cursor="hand2")
        if is_rtl:
            self.box.pack(side="right")
            self.lbl.pack(side="right", padx=(0, 8))
        else:
            self.box.pack(side="left")
            self.lbl.pack(side="left", padx=(8, 0))
        for w in (self.box, self.lbl):
            w.bind("<Button-1>", self.toggle)
        self.draw()

    def set_text(self, text):
        self.lbl.configure(text=text)

    def toggle(self, _=None):
        self.variable.set(not self.variable.get())
        self.draw()
        if self.command:
            self.command()

    def draw(self):
        self.box.delete("all")
        on = bool(self.variable.get())
        fill = C["accent"] if on else C["input"]
        outline = C["accent"] if on else C["border"]
        _rounded(self.box, 1, 1, 21, 21, 5, fill, outline, 1)
        if on:
            self.box.create_line(5, 11, 9, 16, 17, 6, fill=C["accent_text"],
                                 width=2, capstyle="round", joinstyle="round")


def pick_family(root):
    from tkinter import font as tkfont
    available = set(tkfont.families(root))
    for name in ("Segoe UI", "Tahoma", "Calibri", "Arial"):
        if name in available:
            return name
    return "Tahoma"


def apply_theme(root, family):
    from tkinter import ttk
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", background=C["bg"], foreground=C["text"], font=(family, 11))
    style.configure("TFrame", background=C["bg"])
    style.configure("Card.TFrame", background=C["card"])
    style.configure("Header.TFrame", background=C["header"])
    style.configure("Status.TFrame", background=C["status"])
    style.configure("TLabel", background=C["bg"], foreground=C["text"], font=(family, 11))
    style.configure("Card.TLabel", background=C["card"], foreground=C["text"], font=(family, 11))
    style.configure("Muted.TLabel", background=C["card"], foreground=C["muted"], font=(family, 10))
    style.configure("Title.TLabel", background=C["header"], foreground=C["text"], font=(family, 18, "bold"))
    style.configure("Sub.TLabel", background=C["header"], foreground=C["muted"], font=(family, 10))
    style.configure("Status.TLabel", background=C["status"], foreground=C["muted"], font=(family, 9))

    style.configure("TCheckbutton", background=C["card"], foreground=C["text"],
                    font=(family, 11), focuscolor=C["card"], indicatorcolor=C["input"])
    style.map("TCheckbutton",
              background=[("active", C["card"])],
              foreground=[("active", C["text"])],
              indicatorcolor=[("selected", C["accent"]), ("!selected", C["input"])])

    style.configure("TNotebook", background=C["card"], borderwidth=0, tabmargins=(8, 8, 8, 0),
                    lightcolor=C["card"], darkcolor=C["card"], bordercolor=C["card"], relief="flat")
    style.configure("TNotebook.Tab", background=C["input"], foreground=C["muted"],
                    padding=(18, 8), font=(family, 11, "bold"), borderwidth=0, lightcolor=C["card"],
                    darkcolor=C["card"], bordercolor=C["card"])
    style.map("TNotebook.Tab",
              background=[("selected", C["accent_dim"]), ("active", C["border"])],
              foreground=[("selected", C["accent"]), ("active", C["text"])],
              lightcolor=[("selected", C["accent_dim"])],
              expand=[("selected", [0, 0, 0, 0])])

    style.configure("Treeview", background=C["tree"], fieldbackground=C["tree"],
                    foreground=C["text"], font=(family, 10), rowheight=30,
                    borderwidth=0, relief="flat", lightcolor=C["tree"],
                    darkcolor=C["tree"], bordercolor=C["tree"])
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    style.map("Treeview",
              background=[("selected", C["accent"])],
              foreground=[("selected", C["accent_text"])])
    style.configure("Treeview.Item", padding=(4, 2))

    style.configure("Vertical.TScrollbar", background=C["border"], troughcolor=C["tree"],
                    bordercolor=C["tree"], arrowcolor=C["muted"], lightcolor=C["border"],
                    darkcolor=C["border"], relief="flat", width=12)
    style.map("Vertical.TScrollbar",
              background=[("active", C["muted"]), ("!active", C["border"])],
              arrowcolor=[("active", C["text"])])

    style.configure("TEntry", fieldbackground=C["input"], foreground=C["text"],
                    insertcolor=C["accent"], bordercolor=C["border"], lightcolor=C["border"],
                    darkcolor=C["border"], padding=6, font=(family, 11))
    style.map("TEntry",
              fieldbackground=[("focus", C["input"])],
              bordercolor=[("focus", C["accent"])],
              lightcolor=[("focus", C["accent"])],
              darkcolor=[("focus", C["accent"])])

    style.configure("TCombobox", fieldbackground=C["input"], background=C["input"],
                    foreground=C["text"], arrowcolor=C["accent"], bordercolor=C["border"],
                    lightcolor=C["border"], darkcolor=C["border"], padding=5, font=(family, 11))
    style.map("TCombobox",
              fieldbackground=[("readonly", C["input"]), ("focus", C["input"])],
              foreground=[("readonly", C["text"])],
              bordercolor=[("focus", C["accent"])],
              arrowcolor=[("active", C["accent_hover"])])
    root.option_add("*TCombobox*Listbox.background", C["input"])
    root.option_add("*TCombobox*Listbox.foreground", C["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", C["accent_text"])
    root.option_add("*TCombobox*Listbox.font", (family, 11))


def _card(parent):
    from tkinter import ttk
    wrap = tk.Frame(parent, bg=C["bg"], highlightthickness=0)
    outer = tk.Frame(wrap, bg=C["border"], highlightthickness=0)
    inner = ttk.Frame(outer, style="Card.TFrame")
    outer.pack(fill="both", expand=True, padx=0, pady=0)
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    return wrap, inner


def gui(preview=False, lang_override=None, expand=False, start_tab="GPU"):
    from tkinter import ttk

    set_dpi_aware()
    lang = lang_override if lang_override in ("fa", "en") else load_lang()
    persist_choice = [True]
    entries_text = {"GPU": "", "CPU": ""}
    vram_index = [0]
    tab_index = [0 if (start_tab or "GPU").upper() != "CPU" else 1]
    open_cats = {
        "GPU": {"nvidia_50", "nvidia_40", "fun"} if expand else set(),
        "CPU": {"intel_ultra", "amd_ryzen", "fun"} if expand else set(),
    }

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("amirreza.HardwareNameChanger")
    except Exception:
        pass

    root = tk.Tk()
    root.configure(bg=C["bg"])
    root.geometry("740x720")
    root.minsize(640, 620)
    family = pick_family(root)
    apply_theme(root, family)
    fonts = {
        "title": (family, 18, "bold"),
        "sub": (family, 10),
        "body": (family, 11),
        "btn": (family, 11, "bold"),
        "lang": (family, 9, "bold"),
        "status": (family, 9),
        "emoji": (family, 22),
    }

    def S():
        return STRINGS[lang]

    def rtl():
        return lang == "fa"

    def side():
        return "right" if rtl() else "left"

    def anchor():
        return "e" if rtl() else "w"

    ui = {}

    def snapshot_trees():
        trees = ui.get("trees")
        if not trees:
            return
        for kind, tree in trees.items():
            keys = set()
            for iid in tree.get_children():
                vals = tree.item(iid, "values")
                key = vals[0] if vals else ""
                if key and tree.item(iid, "open"):
                    keys.add(key)
            open_cats[kind] = keys
            if kind in ui.get("entries", {}):
                entries_text[kind] = ui["entries"][kind].get()

    def fill_tree(tree, kind):
        tree.delete(*tree.get_children())
        cats = S()["cat"][kind]
        even = False
        for key, names in PRESETS[kind].items():
            parent = tree.insert("", "end", text=cats[key], values=(key,),
                                 open=key in open_cats[kind], tags=("cat",))
            for n in names:
                tag = "even" if even else "odd"
                tree.insert(parent, "end", text=n, values=("",), tags=(tag, "leaf"))
                even = not even
        tree.tag_configure("cat", font=(family, 10, "bold"), background=C["accent_dim"],
                           foreground=C["accent"])
        tree.tag_configure("odd", background=C["row_odd"], foreground=C["text"])
        tree.tag_configure("even", background=C["row_even"], foreground=C["text"])

    def build():
        for w in root.winfo_children():
            w.destroy()
        ui.clear()
        s = S()
        root.title(s["title"] + "  ⚡")
        start = side()

        def rtl_text(text):
            return ("\u202B" + text + "\u202C") if rtl() else text

        # Status first so the expanding body cannot push it off-screen
        status = tk.Frame(root, bg=C["status"], highlightthickness=0)
        status.pack(fill="x", side="bottom")

        # Header
        header = tk.Frame(root, bg=C["header"], highlightthickness=0)
        header.pack(fill="x", side="top")
        accent_bar = tk.Frame(header, bg=C["accent"], height=3)
        accent_bar.pack(fill="x", side="top")
        head_inner = tk.Frame(header, bg=C["header"])
        head_inner.pack(fill="x", padx=20, pady=(12, 14))

        top_row = tk.Frame(head_inner, bg=C["header"])
        top_row.pack(fill="x")
        switch = LangSwitch(top_row, lang, on_lang, font=fonts["lang"])
        switch.pack(side="left" if rtl() else "right")
        ui["switch"] = switch

        titles = tk.Frame(top_row, bg=C["header"])
        titles.pack(side=start, fill="x", expand=True)
        tk.Label(titles, text="⚡", bg=C["header"], fg=C["accent"],
                 font=fonts["emoji"]).pack(side=start, padx=(0, 10) if not rtl() else (10, 0))
        tk.Label(titles, text=rtl_text(s["header"]), bg=C["header"], fg=C["text"],
                 font=fonts["title"], anchor=anchor(), justify=start).pack(side=start, pady=(0, 0))

        tk.Label(head_inner, text=rtl_text(s["subtitle"]), bg=C["header"], fg=C["muted"],
                 font=fonts["sub"], anchor=anchor(), justify=start,
                 wraplength=680).pack(fill="x", pady=(6, 0))

        # Body
        body = tk.Frame(root, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=18, pady=(14, 8))

        # Buttons + options reserved at the bottom of the body
        btns = tk.Frame(body, bg=C["bg"])
        btns.pack(side="bottom", fill="x", pady=(12, 4))
        opt_wrap, opt = _card(body)
        opt_wrap.pack(side="bottom", fill="x", pady=(10, 0))

        card_wrap, card = _card(body)
        card_wrap.pack(fill="both", expand=True)

        nb = ttk.Notebook(card)
        nb.pack(fill="both", expand=True, padx=10, pady=(6, 8))
        entries = {}
        trees = {}
        current_labels = {}
        gname, cname = current_names()
        currents = {"GPU": (gname or "").strip() or "?", "CPU": (cname or "").strip() or "?"}

        def on_select(_ev, t=None, ent=None):
            sel = t.selection()
            if not sel:
                return
            iid = sel[0]
            if t.parent(iid):
                ent.delete(0, "end")
                ent.insert(0, t.item(iid, "text"))

        for kind in ("GPU", "CPU"):
            tab = ttk.Frame(nb, style="Card.TFrame")
            nb.add(tab, text=s["tab_gpu"] if kind == "GPU" else s["tab_cpu"])
            tab.columnconfigure(0, weight=1)
            tab.rowconfigure(1, weight=1)

            cur_row = ttk.Frame(tab, style="Card.TFrame")
            cur_row.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
            cap = ttk.Label(cur_row, style="Muted.TLabel", text=rtl_text(s["current_label"]))
            nam = ttk.Label(cur_row, style="Card.TLabel", text=currents[kind])
            if rtl():
                cap.pack(side="right")
                nam.pack(side="right", padx=(0, 8))
            else:
                cap.pack(side="left")
                nam.pack(side="left", padx=(8, 0))
            current_labels[kind] = nam

            tree_wrap = tk.Frame(tab, bg=C["tree"], highlightbackground=C["border"],
                                 highlightthickness=1, bd=0)
            tree_wrap.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))
            tree = ttk.Treeview(tree_wrap, show="tree", height=10, selectmode="browse")
            sb = ttk.Scrollbar(tree_wrap, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            tree.pack(side="left", fill="both", expand=True)
            fill_tree(tree, kind)

            row = ttk.Frame(tab, style="Card.TFrame")
            row.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
            ttk.Label(row, text=rtl_text(s["chosen"]), style="Muted.TLabel").pack(anchor=anchor(), pady=(0, 4))
            e = ttk.Entry(row)
            e.pack(fill="x")
            if entries_text.get(kind):
                e.insert(0, entries_text[kind])
            tree.bind("<<TreeviewSelect>>", lambda ev, t=tree, ent=e: on_select(ev, t, ent))
            entries[kind] = e
            trees[kind] = tree

        ui["nb"] = nb
        ui["entries"] = entries
        ui["trees"] = trees
        ui["current_labels"] = current_labels
        try:
            nb.select(tab_index[0])
        except tk.TclError:
            pass
        nb.bind("<<NotebookTabChanged>>", lambda _e: tab_index.__setitem__(0, nb.index("current")))

        # Options card (already packed at bottom of body)
        opt_inner = ttk.Frame(opt, style="Card.TFrame")
        opt_inner.pack(fill="x", padx=16, pady=12)

        vrow = ttk.Frame(opt_inner, style="Card.TFrame")
        vrow.pack(fill="x")
        ttk.Label(vrow, text=rtl_text(s["vram"]), style="Card.TLabel").pack(side=start)
        vram_opts = [s["vram_none"], *VRAM_GB]
        vram_box = ttk.Combobox(vrow, values=vram_opts, width=16, state="readonly")
        idx = vram_index[0] if vram_index[0] < len(vram_opts) else 0
        vram_box.current(idx)
        vram_box.pack(side=start, padx=10)
        vram_box.bind("<<ComboboxSelected>>", lambda _e: vram_index.__setitem__(0, vram_box.current()))
        ui["vram"] = vram_box

        persist = tk.BooleanVar(value=persist_choice[0])
        chk = FancyCheck(opt_inner, rtl_text(s["persist"]), persist, fonts["body"],
                         is_rtl=rtl(), command=lambda: persist_choice.__setitem__(0, persist.get()))
        chk.pack(anchor=anchor(), pady=(10, 0))
        ui["persist"] = persist

        # Buttons (frame already packed)
        btn_box = tk.Frame(btns, bg=C["bg"])
        btn_box.pack(anchor="center")
        apply_btn = PillButton(btn_box, s["apply"], on_apply, "primary", 220, 44, fonts["btn"])
        restore_btn = PillButton(btn_box, s["restore"], on_restore, "danger", 220, 44, fonts["btn"])
        # Visual order: Apply first in LTR, still Apply visually leading in RTL (right side)
        if rtl():
            restore_btn.pack(side="right", padx=8)
            apply_btn.pack(side="right", padx=8)
        else:
            apply_btn.pack(side="left", padx=8)
            restore_btn.pack(side="left", padx=8)
        ui["apply_btn"] = apply_btn
        ui["restore_btn"] = restore_btn

        # Status bar contents (frame already packed)
        tk.Frame(status, bg=C["border"], height=1).pack(fill="x")
        st_inner = tk.Frame(status, bg=C["status"])
        st_inner.pack(fill="x", padx=18, pady=8)

        def status_pair(parent, label, value):
            box = tk.Frame(parent, bg=C["status"])
            cap = tk.Label(box, text=rtl_text(label + ":"), bg=C["status"], fg=C["muted"], font=fonts["status"])
            val = tk.Label(box, text=value, bg=C["status"], fg=C["text"], font=fonts["status"])
            if rtl():
                cap.pack(side="right")
                val.pack(side="right", padx=(0, 6))
            else:
                cap.pack(side="left")
                val.pack(side="left", padx=(6, 0))
            return box

        gbox = status_pair(st_inner, s["status_gpu"], currents["GPU"])
        cbox = status_pair(st_inner, s["status_cpu"], currents["CPU"])
        dot = tk.Label(st_inner, text="  ·  ", bg=C["status"], fg=C["border"], font=fonts["status"])
        if rtl():
            gbox.pack(side="right")
            dot.pack(side="right")
            cbox.pack(side="right")
        else:
            gbox.pack(side="left")
            dot.pack(side="left")
            cbox.pack(side="left")
        ui["status"] = st_inner

    def on_lang(new_lang):
        nonlocal lang
        if new_lang == lang:
            return
        snapshot_trees()
        if "entries" in ui:
            for kind, e in ui["entries"].items():
                entries_text[kind] = e.get()
        if "vram" in ui:
            vram_index[0] = ui["vram"].current()
        if "persist" in ui:
            persist_choice[0] = ui["persist"].get()
        lang = new_lang
        if not preview:
            save_lang(lang)
        build()

    def parse_vram():
        box = ui["vram"]
        raw = box.get().strip()
        none = S()["vram_none"]
        if not raw or raw == none:
            return None, False
        try:
            num = raw.replace("GB", "").replace("gb", "").strip()
            return int(float(num) * 1024 ** 3), False
        except ValueError:
            return None, True

    def on_apply():
        s = S()
        if preview:
            messagebox.showinfo(s["preview_title"], s["preview_apply"])
            return
        gpu = ui["entries"]["GPU"].get().strip()
        cpu = ui["entries"]["CPU"].get().strip()
        vram, bad = parse_vram()
        if bad:
            messagebox.showwarning(s["invalid_num_title"], s["invalid_num"])
            return
        if not gpu and not cpu and not vram:
            messagebox.showwarning(s["nothing_title"], s["nothing"])
            return
        try:
            apply(gpu, cpu, ui["persist"].get(), vram)
            messagebox.showinfo(s["done_title"], s["done"])
            snapshot_trees()
            if "entries" in ui:
                for kind, e in ui["entries"].items():
                    entries_text[kind] = e.get()
            build()
        except Exception as ex:
            messagebox.showerror(s["error"], str(ex))

    def on_restore():
        s = S()
        if preview:
            messagebox.showinfo(s["preview_title"], s["preview_restore"])
            return
        try:
            restore()
            messagebox.showinfo(s["restored_title"], s["restored"])
            snapshot_trees()
            build()
        except NoBackupError:
            messagebox.showerror(s["error"], s["no_backup"])
        except Exception as ex:
            messagebox.showerror(s["error"], str(ex))

    build()
    root.mainloop()


def main():
    argv = sys.argv[1:]
    if "--system" in argv or "--apply-cpu" in argv:
        system_mode()
        return
    preview = "--preview" in argv
    expand = "--expand" in argv
    lang = None
    start_tab = "GPU"
    if "--lang" in argv:
        i = argv.index("--lang")
        if i + 1 < len(argv) and argv[i + 1].lower() in ("fa", "en"):
            lang = argv[i + 1].lower()
    if "--tab" in argv:
        i = argv.index("--tab")
        if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
            start_tab = "CPU" if argv[i + 1].lower() == "cpu" else "GPU"
    if not preview and not is_admin():
        exe = sys.executable
        if getattr(sys, "frozen", False):
            params = " ".join(argv)
        else:
            params = " ".join([f'"{os.path.abspath(__file__)}"'] + argv)
        ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        return
    gui(preview=preview, lang_override=lang, expand=expand, start_tab=start_tab)


if __name__ == "__main__":
    main()
