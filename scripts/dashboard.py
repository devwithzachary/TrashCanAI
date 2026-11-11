#!/usr/bin/env python3
"""
TrashCan-Top: Real-time Terminal Dashboard for 2013 Mac Pro AI Server
Monitors Xeon 12C/24T CPU, 64GB Quad-Channel RAM, Dual AMD FirePro D500 GPUs (with live GPU load %),
system/component power draw (Intel RAPL + Apple SMC), and active llama.cpp processes.
"""

import argparse
import glob
import json
import math
import os
import re
import struct
import subprocess
import sys
import threading
import time
import urllib.request

import psutil
from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

SMC_DIR = "/sys/devices/platform/applesmc.768"
RAPL_GLOB = "/sys/class/powercap/intel-rapl:*"
PSU_MAX_WATTS = 450.0
WALL_IDLE_BASELINE_WATTS = 120.0

SMC_SYSTEM_KEYS = (
    ("PSTR", "SMC PSTR Total"),
    ("PDTR", "SMC PDTR DC-In"),
    ("PPTR", "SMC PPTR Platform"),
    ("PHPC", "SMC PHPC Total"),
)
SMC_CPU_KEYS = ("PCPC", "PCTR", "PC0R", "PC0C")
SMC_GPU0_KEYS = ("PG0R", "PG0C", "PD0R")
SMC_GPU1_KEYS = ("PG1R", "PG1C", "PD1R")
SMC_MEM_KEYS = ("PM0R", "PMVR", "PMTR")

# Background GPU load tracker via radeontop
gpu_load_data = {"02": 0.0, "06": 0.0}
stop_gpu_threads = False
_gpu_threads_started = False


def radeontop_worker(bus_id):
    """Background worker that continuously reads GPU load from radeontop."""
    global stop_gpu_threads
    while not stop_gpu_threads:
        try:
            cmd = ["radeontop", "-b", bus_id, "-d", "-"]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            while not stop_gpu_threads:
                line = proc.stdout.readline()
                if not line:
                    break
                m = re.search(r"gpu\s+([\d\.]+)%", line)
                if m:
                    gpu_load_data[bus_id] = float(m.group(1))
            proc.terminate()
            proc.wait(timeout=1.0)
        except Exception:
            time.sleep(1.0)


def start_gpu_threads():
    """Start daemon radeontop threads once when running live dashboard."""
    global _gpu_threads_started
    if _gpu_threads_started:
        return
    _gpu_threads_started = True
    for bus_id in ("02", "06"):
        t = threading.Thread(target=radeontop_worker, args=(bus_id,), daemon=True)
        t.start()


def decode_smc_value(smc_type: str, raw_bytes: bytes):
    """Decode raw Apple SMC payload according to its FourCC type descriptor."""
    t = smc_type.rstrip("\x00\r\n ").lower()
    if not raw_bytes:
        return None

    try:
        if t == "flt" and len(raw_bytes) >= 4:
            # Intel/x86 Apple SMC stores IEEE-754 float32 as little-endian.
            val = struct.unpack("<f", raw_bytes[:4])[0]
            return float(val) if math.isfinite(val) else None

        if len(t) == 4 and t.startswith("sp") and len(raw_bytes) >= 2:
            frac_bits = int(t[3], 16)
            return struct.unpack(">h", raw_bytes[:2])[0] / float(1 << frac_bits)

        if len(t) == 4 and t.startswith("fp") and len(raw_bytes) >= 2:
            frac_bits = int(t[3], 16)
            return struct.unpack(">H", raw_bytes[:2])[0] / float(1 << frac_bits)

        int_formats = {
            "ui8": (">B", 1),
            "ui16": (">H", 2),
            "ui32": (">I", 4),
            "si8": (">b", 1),
            "si16": (">h", 2),
            "si32": (">i", 4),
        }
        if t in int_formats:
            fmt, need = int_formats[t]
            if len(raw_bytes) >= need:
                return float(struct.unpack(fmt, raw_bytes[:need])[0])
    except (ValueError, struct.error):
        return None
    return None


class PowerMonitor:
    """Samples live wattage from Intel RAPL (CPU/DRAM) and Apple SMC (System/GPU rails)."""

    def __init__(self, smc_dir=SMC_DIR, rapl_glob=RAPL_GLOB, prime_sleep=0.25):
        self.smc_dir = smc_dir
        self.rapl_glob = rapl_glob
        self.rapl_domains = self._discover_rapl()
        self.rapl_prev = {}
        self.rapl_perm_denied = False
        self.smc_keys = {}
        self.smc_perm_denied = False
        self.smc_available = os.path.exists(os.path.join(self.smc_dir, "key_count"))
        self.min_w = None
        self.peak_w = None

        self._init_smc()
        self._prime_rapl(prime_sleep)

    def _discover_rapl(self):
        domains = []
        for path in sorted(glob.glob(self.rapl_glob)):
            name_file = os.path.join(path, "name")
            energy_file = os.path.join(path, "energy_uj")
            if not (os.path.exists(name_file) and os.path.exists(energy_file)):
                continue
            try:
                with open(name_file, "r") as f:
                    name = f.read().strip()
                max_range = 0
                max_file = os.path.join(path, "max_energy_range_uj")
                if os.path.exists(max_file):
                    with open(max_file, "r") as mf:
                        max_range = int(mf.read().strip())
                domains.append({
                    "id": os.path.basename(path),
                    "path": path,
                    "name": name,
                    "energy_file": energy_file,
                    "max_range": max_range,
                })
            except Exception:
                continue
        return domains

    def _prime_rapl(self, prime_sleep):
        if not self.rapl_domains:
            return
        now = time.monotonic()
        any_ok = False
        for d in self.rapl_domains:
            try:
                with open(d["energy_file"], "r") as f:
                    uj = int(f.read().strip())
                self.rapl_prev[d["path"]] = (now, uj)
                any_ok = True
            except PermissionError:
                self.rapl_perm_denied = True
            except Exception:
                continue
        if any_ok and prime_sleep > 0:
            time.sleep(prime_sleep)

    def _init_smc(self):
        if not self.smc_available:
            return
        idx_path = os.path.join(self.smc_dir, "key_at_index")
        count_path = os.path.join(self.smc_dir, "key_count")
        name_path = os.path.join(self.smc_dir, "key_at_index_name")
        type_path = os.path.join(self.smc_dir, "key_at_index_type")
        len_path = os.path.join(self.smc_dir, "key_at_index_data_length")
        try:
            with open(count_path, "r") as cf:
                key_count = int(cf.read().strip())
            for idx in range(key_count):
                with open(idx_path, "w") as idxf:
                    idxf.write(str(idx))
                with open(name_path, "r") as nf:
                    key_name = nf.read().rstrip("\x00\r\n")
                if not key_name.startswith("P"):
                    continue
                with open(type_path, "r") as tf:
                    smc_type = tf.read().rstrip("\x00\r\n")
                with open(len_path, "r") as lf:
                    data_len = int(lf.read().strip())
                self.smc_keys[key_name] = {
                    "idx": idx,
                    "type": smc_type,
                    "len": data_len,
                }
        except PermissionError:
            self.smc_perm_denied = True
        except Exception:
            pass

    def _read_smc_power_rails(self):
        readings = {}
        probe_rows = []
        if not self.smc_keys:
            return readings, probe_rows

        idx_path = os.path.join(self.smc_dir, "key_at_index")
        data_path = os.path.join(self.smc_dir, "key_at_index_data")
        for key_name, meta in self.smc_keys.items():
            try:
                with open(idx_path, "w") as idxf:
                    idxf.write(str(meta["idx"]))
                with open(data_path, "rb") as df:
                    raw = df.read()
                val = decode_smc_value(meta["type"], raw)
                probe_rows.append({
                    "key": key_name,
                    "type": meta["type"],
                    "raw_hex": raw.hex(),
                    "value": val,
                })
                if val is not None and 0.0 <= val <= 650.0:
                    readings[key_name] = val
            except PermissionError:
                self.smc_perm_denied = True
                break
            except Exception:
                continue
        return readings, probe_rows

    def _read_rapl_watts(self):
        watts = {}
        now = time.monotonic()
        for d in self.rapl_domains:
            try:
                with open(d["energy_file"], "r") as f:
                    uj = int(f.read().strip())
                prev = self.rapl_prev.get(d["path"])
                self.rapl_prev[d["path"]] = (now, uj)
                if prev is None:
                    continue
                prev_t, prev_uj = prev
                dt = now - prev_t
                if dt < 0.05:
                    continue
                delta = uj - prev_uj
                if delta < 0 and d["max_range"] > 0:
                    delta += d["max_range"]
                if delta >= 0:
                    w = (delta / 1_000_000.0) / dt
                    if 0.0 <= w <= 1000.0:
                        watts[d["name"]] = w
            except PermissionError:
                self.rapl_perm_denied = True
            except Exception:
                continue
        return watts

    def _read_amdgpu_debugfs_watts(self):
        gpu_watts = []
        for pm_file in sorted(glob.glob("/sys/kernel/debug/dri/*/amdgpu_pm_info")):
            try:
                with open(pm_file, "r") as f:
                    content = f.read()
                m = re.search(r"([\d\.]+)\s*W\s*\((?:average\s+GPU|VDDC)\)", content)
                if m:
                    gpu_watts.append(float(m.group(1)))
            except Exception:
                continue
        return gpu_watts

    @staticmethod
    def _pick_first_key(readings, keys, min_val=0.0):
        for k in keys:
            if k in readings and readings[k] > min_val:
                return k, readings[k]
        return None, None

    def sample(self, include_probe=False):
        """Return measured power snapshot without mixing unmeasured estimates into hardware reads."""
        smc_readings, probe_rows = self._read_smc_power_rails()
        rapl_watts = self._read_rapl_watts()
        debugfs_gpus = self._read_amdgpu_debugfs_watts() if not smc_readings else []

        sys_key, system_w = self._pick_first_key(
            smc_readings, [k for k, _ in SMC_SYSTEM_KEYS], min_val=1.0
        )
        sys_label_map = dict(SMC_SYSTEM_KEYS)

        cpu_smc_key, cpu_smc_w = self._pick_first_key(smc_readings, SMC_CPU_KEYS, min_val=0.05)
        gpu0_key, gpu0_w = self._pick_first_key(smc_readings, SMC_GPU0_KEYS, min_val=0.05)
        gpu1_key, gpu1_w = self._pick_first_key(smc_readings, SMC_GPU1_KEYS, min_val=0.05)
        mem_smc_key, mem_smc_w = self._pick_first_key(smc_readings, SMC_MEM_KEYS, min_val=0.05)

        if gpu0_w is None and len(debugfs_gpus) >= 1:
            gpu0_w = debugfs_gpus[0]
        if gpu1_w is None and len(debugfs_gpus) >= 2:
            gpu1_w = debugfs_gpus[1]

        cpu_pkg_w = rapl_watts.get("package-0")
        if cpu_pkg_w is None:
            cpu_pkg_w = cpu_smc_w
        cpu_core_w = rapl_watts.get("core")
        dram_w = rapl_watts.get("dram")
        if dram_w is None:
            dram_w = mem_smc_w

        headline_w = None
        headline_kind = "unavailable"
        headline_label = "No live sensor"
        if system_w is not None:
            headline_w = system_w
            headline_kind = "system"
            headline_label = sys_label_map.get(sys_key, f"SMC {sys_key}")
        else:
            parts = []
            subtotal = 0.0
            if cpu_pkg_w is not None:
                subtotal += cpu_pkg_w
                parts.append("CPU")
            if dram_w is not None:
                subtotal += dram_w
                parts.append("DRAM")
            if gpu0_w is not None or gpu1_w is not None:
                subtotal += (gpu0_w or 0.0) + (gpu1_w or 0.0)
                parts.append("GPU")
            if parts:
                headline_w = subtotal
                headline_kind = "partial"
                headline_label = "+".join(parts) + " Measured"

        if headline_w is not None and headline_w > 0:
            self.min_w = headline_w if self.min_w is None else min(self.min_w, headline_w)
            self.peak_w = headline_w if self.peak_w is None else max(self.peak_w, headline_w)

        snap = {
            "headline_w": headline_w,
            "headline_kind": headline_kind,
            "headline_label": headline_label,
            "system_w": system_w,
            "system_key": sys_key,
            "cpu_pkg_w": cpu_pkg_w,
            "cpu_core_w": cpu_core_w,
            "cpu_smc_key": cpu_smc_key,
            "dram_w": dram_w,
            "mem_smc_key": mem_smc_key,
            "gpu0_w": gpu0_w,
            "gpu0_key": gpu0_key,
            "gpu1_w": gpu1_w,
            "gpu1_key": gpu1_key,
            "min_w": self.min_w,
            "peak_w": self.peak_w,
            "rapl_watts": rapl_watts,
            "smc_readings": smc_readings,
            "requires_root": self.rapl_perm_denied or self.smc_perm_denied,
            "rapl_denied": self.rapl_perm_denied,
            "smc_denied": self.smc_perm_denied,
        }
        if include_probe:
            snap["probe_rows"] = probe_rows
        return snap

def get_cpu_info():
    """Reads CPU utilization, core temps, and frequency."""
    cpu_pct = psutil.cpu_percent(interval=None)
    cpu_freq = psutil.cpu_freq()
    freq_mhz = cpu_freq.current if cpu_freq else 2700.0

    temp_c = 0.0
    for hw in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            name_file = os.path.join(hw, "name")
            if os.path.exists(name_file):
                with open(name_file, "r") as f:
                    if "coretemp" in f.read():
                        temp_file = os.path.join(hw, "temp1_input")
                        if os.path.exists(temp_file):
                            with open(temp_file, "r") as tf:
                                temp_c = int(tf.read().strip()) / 1000.0
                                break
        except Exception:
            pass

    return {
        "pct": cpu_pct,
        "freq_mhz": freq_mhz,
        "temp_c": temp_c,
    }

def get_ram_info():
    """Reads system memory and swap usage."""
    vm = psutil.virtual_memory()
    sm = psutil.swap_memory()
    return {
        "total_gb": vm.total / (1024**3),
        "used_gb": vm.used / (1024**3),
        "avail_gb": vm.available / (1024**3),
        "pct": vm.percent,
        "swap_used_gb": sm.used / (1024**3),
        "swap_total_gb": sm.total / (1024**3),
    }

def get_gpu_info():
    """Reads sysfs stats and live radeontop load for AMD FirePro D500 GPUs."""
    gpus = []
    card_paths = sorted(glob.glob("/sys/class/drm/card[0-9]"))
    for card in card_paths:
        device_dir = os.path.join(card, "device")
        vendor_file = os.path.join(device_dir, "vendor")
        if not os.path.exists(vendor_file):
            continue
        try:
            with open(vendor_file, "r") as f:
                if f.read().strip() != "0x1002":
                    continue
        except Exception:
            continue

        gpu_id = os.path.basename(card)
        pci_slot = "Unknown"
        bus_hex = "02"
        try:
            uevent = os.path.join(device_dir, "uevent")
            if os.path.exists(uevent):
                with open(uevent, "r") as f:
                    for line in f:
                        if line.startswith("PCI_SLOT_NAME="):
                            raw_pci = line.split("=")[1].strip()
                            pci_slot = raw_pci.replace("0000:", "")
                            # extract bus e.g. "02" or "06"
                            bus_hex = pci_slot.split(":")[0]
        except Exception:
            pass

        # VRAM
        vram_used_mb = 0.0
        vram_total_mb = 3072.0
        used_f = os.path.join(device_dir, "mem_info_vram_used")
        tot_f = os.path.join(device_dir, "mem_info_vram_total")
        try:
            if os.path.exists(used_f):
                with open(used_f, "r") as f:
                    vram_used_mb = int(f.read().strip()) / (1024 * 1024)
            if os.path.exists(tot_f):
                with open(tot_f, "r") as f:
                    vram_total_mb = int(f.read().strip()) / (1024 * 1024)
        except Exception:
            pass

        # Sensors
        temp_c = 0.0
        sclk_mhz = 0.0
        mclk_mhz = 0.0
        hwmon_dirs = glob.glob(os.path.join(device_dir, "hwmon", "hwmon*"))
        if hwmon_dirs:
            hw = hwmon_dirs[0]
            try:
                tf = os.path.join(hw, "temp1_input")
                if os.path.exists(tf):
                    with open(tf, "r") as f:
                        temp_c = int(f.read().strip()) / 1000.0
                f1 = os.path.join(hw, "freq1_input")
                if os.path.exists(f1):
                    with open(f1, "r") as f:
                        sclk_mhz = int(f.read().strip()) / 1000000.0
                f2 = os.path.join(hw, "freq2_input")
                if os.path.exists(f2):
                    with open(f2, "r") as f:
                        mclk_mhz = int(f.read().strip()) / 1000000.0
            except Exception:
                pass

        vram_pct = (vram_used_mb / vram_total_mb * 100) if vram_total_mb > 0 else 0.0
        gpu_load = gpu_load_data.get(bus_hex, 0.0)

        gpus.append({
            "id": gpu_id,
            "pci": pci_slot,
            "bus": bus_hex,
            "name": "AMD FirePro D500",
            "vram_used_mb": vram_used_mb,
            "vram_total_mb": vram_total_mb,
            "vram_pct": vram_pct,
            "gpu_load_pct": gpu_load,
            "temp_c": temp_c,
            "sclk_mhz": sclk_mhz,
            "mclk_mhz": mclk_mhz,
        })
    return gpus

def _extract_flag(cmd, *names, default=None):
    """Extract flag value from tokenized argv supporting '--flag val' and '--flag=val'."""
    for i, tok in enumerate(cmd):
        for name in names:
            if tok == name and i + 1 < len(cmd):
                return cmd[i + 1]
            if tok.startswith(name + "="):
                return tok.split("=", 1)[1]
    return default


def parse_proc_details(proc):
    """Extracts model and inference flags from llama.cpp process argv."""
    cmd = proc.info.get("cmdline") or []
    cmd_str = " ".join(cmd)

    model_path = _extract_flag(cmd, "-m", "--model")
    alias = _extract_flag(cmd, "-a", "--alias")
    ngl = _extract_flag(cmd, "-ngl", "--n-gpu-layers", default="99")
    split = _extract_flag(cmd, "-sm", "--split-mode", default="layer")
    ts = _extract_flag(cmd, "-ts", "--tensor-split", default="1,1")
    ctx = _extract_flag(cmd, "-c", "--ctx-size", default="4096")
    threads = _extract_flag(cmd, "-t", "--threads", default="12")
    slots = _extract_flag(cmd, "-np", "--parallel", default="1")
    port = _extract_flag(cmd, "--port", default="8080")
    fa = _extract_flag(cmd, "-fa", "--flash-attn")
    preset = _extract_flag(cmd, "--models-preset", "--models-dir")

    base_model = os.path.basename(model_path) if model_path else None
    if alias and base_model:
        model_name = f"{alias} ({base_model})"
    elif base_model:
        model_name = base_model
    elif alias:
        model_name = alias
    elif preset:
        model_name = f"Router Standby ({os.path.basename(preset)})"
    else:
        model_name = "Unknown Model"

    return {
        "pid": proc.info["pid"],
        "name": proc.info["name"],
        "cpu_pct": proc.cpu_percent(),
        "mem_mb": proc.info["memory_info"].rss / (1024 * 1024) if proc.info.get("memory_info") else 0,
        "model": model_name,
        "alias": alias,
        "has_model": bool(model_path),
        "is_router": bool(preset and not model_path),
        "ngl": ngl,
        "split": split,
        "ts": ts,
        "ctx": ctx,
        "threads": threads,
        "slots": slots,
        "port": port,
        "fa": fa,
        "cmdline": cmd_str,
    }


def _fetch_metrics(metrics_url):
    """Fetch Prometheus metrics from llama-server."""
    req = urllib.request.Request(metrics_url, headers={'User-Agent': 'TrashTop/1.0'})
    with urllib.request.urlopen(req, timeout=0.3) as resp:
        text = resp.read().decode('utf-8', errors='ignore')
    metrics = {}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 2:
            metrics[parts[0]] = parts[1]
    return metrics


def get_all_llama_processes():
    """Finds all llama.cpp related processes, categorized by role."""
    bench_proc = None
    cli_proc = None
    router_proc = None
    worker_procs = []

    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cpu_percent', 'memory_info']):
        try:
            cmd = proc.info.get('cmdline') or []
            if not cmd:
                continue
            exe = os.path.basename(cmd[0])
            if exe == "llama-bench":
                bench_proc = parse_proc_details(proc)
            elif exe in ("llama-cli", "llama-mtmd-cli"):
                cli_proc = parse_proc_details(proc)
            elif exe == "llama-server":
                info = parse_proc_details(proc)
                if info["is_router"]:
                    router_proc = info
                else:
                    worker_procs.append(info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    server_proc = worker_procs[-1] if worker_procs else router_proc
    if server_proc and router_proc and server_proc is not router_proc:
        server_proc["router_port"] = router_proc["port"]
        server_proc["mem_mb"] += router_proc["mem_mb"]
        server_proc["cpu_pct"] += router_proc["cpu_pct"]

    # Query metrics from active worker or router endpoint
    server_metrics = None
    if server_proc and server_proc["has_model"]:
        urls = [f"http://127.0.0.1:{server_proc['port']}/metrics"]
        if server_proc.get("alias"):
            rport = server_proc.get("router_port", "8080")
            urls.append(f"http://127.0.0.1:{rport}/metrics?model={server_proc['alias']}")
        for murl in urls:
            try:
                server_metrics = _fetch_metrics(murl)
                if server_metrics:
                    break
            except Exception:
                continue
        server_proc["server_metrics"] = server_metrics

    return {
        "bench": bench_proc,
        "cli": cli_proc,
        "server": server_proc,
    }

def bar(pct, width=14, color="cyan"):
    """Renders a styled Unicode progress bar."""
    filled = max(0, min(width, int(round(width * (pct / 100.0)))))
    empty = width - filled
    return f"[{color}]{'█' * filled}[/][grey37]{'░' * empty}[/]"

def _render_power_panel(power, gen_tps=0.0):
    """Build the System Power & Efficiency Rich panel."""
    if not power or power["headline_w"] is None:
        locked_t = Text.from_markup(
            "[bold yellow]Sensors:[/] [bold red]Root permission required[/] for Intel RAPL & Apple SMC hardware Watts\n"
            f"[bold yellow]Run:[/]     [bold cyan]sudo trash-top[/]  [dim](Wall idle ref: ~{WALL_IDLE_BASELINE_WATTS:.0f} W  |  PSU ceiling: {PSU_MAX_WATTS:.0f} W)[/]"
        )
        return Panel(
            locked_t,
            title="[dim]⚡ SYSTEM POWER & EFFICIENCY [RUN 'sudo trash-top'][/]",
            box=box.ROUNDED,
            style="dim",
        )

    watts = power["headline_w"]
    is_full_sys = power["headline_kind"] == "system"
    scale_max = PSU_MAX_WATTS if is_full_sys else 300.0
    bar_pct = min(100.0, (watts / scale_max) * 100.0)
    p_col = "green" if watts < 145.0 else ("yellow" if watts < 240.0 else "red")

    min_part = f"  |  Min: [bold green]{power['min_w']:.1f} W[/]" if power["min_w"] is not None else ""
    peak_part = f"  |  Peak: [bold red]{power['peak_w']:.1f} W[/]" if power["peak_w"] is not None else ""
    line1 = (
        f"[bold yellow]Draw:[/]  {bar(bar_pct, 16, p_col)} [{p_col}]{watts:5.1f} W[/] "
        f"[dim]({power['headline_label']})[/]{min_part}{peak_part}"
    )

    rails = []
    if power["cpu_pkg_w"] is not None:
        core_suffix = f" [dim](Core {power['cpu_core_w']:.0f}W)[/]" if power["cpu_core_w"] is not None else ""
        rails.append(f"[bold cyan]CPU:[/] {power['cpu_pkg_w']:.1f}W{core_suffix}")
    if power["dram_w"] is not None:
        rails.append(f"[bold cyan]DRAM:[/] {power['dram_w']:.1f}W")
    if power["gpu0_w"] is not None:
        rails.append(f"[bold magenta]GPU0:[/] {power['gpu0_w']:.1f}W")
    if power["gpu1_w"] is not None:
        rails.append(f"[bold magenta]GPU1:[/] {power['gpu1_w']:.1f}W")

    if power["gpu0_w"] is None and power["gpu1_w"] is None and power["smc_readings"]:
        skip = {power.get("system_key"), power.get("cpu_smc_key"), power.get("mem_smc_key")}
        extras = [(k, v) for k, v in sorted(power["smc_readings"].items()) if k not in skip and v > 0.5]
        for k, v in extras[:3]:
            rails.append(f"[white]{k}:[/] {v:.1f}W")

    if gen_tps > 0.0 and watts > 0.0:
        eff_tok_w = gen_tps / watts
        j_per_tok = watts / gen_tps
        rails.append(f"[bold green]Eff:[/] {eff_tok_w:.3f} tok/s/W [dim]({j_per_tok:.1f} J/tok)[/]")
    elif not is_full_sys and power["smc_denied"]:
        rails.append("[dim]Run 'sudo trash-top' for full SMC system & GPU W[/]")

    line2 = "[bold yellow]Rails:[/] " + (" | ".join(rails) if rails else "[dim]Sampling telemetry...[/]")
    title = (
        "[bold yellow]⚡ SYSTEM POWER & EFFICIENCY [LIVE][/]"
        if is_full_sys
        else "[bold yellow]⚡ SUBSYSTEM POWER & EFFICIENCY [RAPL][/]"
    )
    style = "yellow" if watts >= 165.0 else "white"
    return Panel(Text.from_markup(f"{line1}\n{line2}"), title=title, box=box.ROUNDED, style=style)


def render_dashboard(power_monitor=None):
    cpu = get_cpu_info()
    ram = get_ram_info()
    gpus = get_gpu_info()
    llama_procs = get_all_llama_processes()

    # 1. Header
    header = Panel(
        Text.from_markup("[bold black on bright_yellow] 🗑️  TRASHCAN-AI [/]  [bold white]Mac Pro 2013 (MacPro6,1) // Dual AMD FirePro D500 AI Workstation[/]"),
        box=box.ROUNDED,
        style="yellow"
    )

    # 2. CPU & RAM (Two Columns)
    cpu_color = "green" if cpu["pct"] < 60 else ("yellow" if cpu["pct"] < 85 else "red")
    cpu_text = Text.from_markup(
        f"[bold cyan]CPU:[/]  Xeon E5-2697 v2 [dim](12C/24T)[/]\n"
        f"[bold cyan]Load:[/] {bar(cpu['pct'], 14, cpu_color)} [{cpu_color}]{cpu['pct']:5.1f}%[/]\n"
        f"[bold cyan]Temp:[/] [bold yellow]{cpu['temp_c']:.1f}°C[/]  |  Clock: [bold cyan]{cpu['freq_mhz']:.0f} MHz[/]\n"
        f"[bold cyan]Arch:[/] [bold green]AVX[/] + [bold green]F16C[/] [dim](Ivy Bridge)[/]"
    )

    ram_color = "green" if ram["pct"] < 70 else ("yellow" if ram["pct"] < 85 else "red")
    ram_text = Text.from_markup(
        f"[bold cyan]Pool:[/] 64 GB Quad-Channel DDR3\n"
        f"[bold cyan]Used:[/] {bar(ram['pct'], 14, ram_color)} [{ram_color}]{ram['pct']:5.1f}%[/]\n"
        f"[bold cyan]Mem:[/]  [bold cyan]{ram['used_gb']:.1f} GB[/] / [white]{ram['total_gb']:.1f} GB[/] [dim]({ram['avail_gb']:.1f}G free)[/]\n"
        f"[bold cyan]Swap:[/] [dim]{ram['swap_used_gb']:.1f} GB / {ram['swap_total_gb']:.1f} GB[/]"
    )

    t_sys = Table.grid(expand=True)
    t_sys.add_column(ratio=1)
    t_sys.add_column(ratio=1)
    t_sys.add_row(
        Panel(cpu_text, title="[bold cyan]Processor (12-Core Xeon)[/]", box=box.ROUNDED),
        Panel(ram_text, title="[bold cyan]System Memory (64 GB)[/]", box=box.ROUNDED)
    )

    # 3. Dual GPUs (Two Columns with live GPU Load % and VRAM %)
    t_gpu = Table.grid(expand=True)
    t_gpu.add_column(ratio=1)
    t_gpu.add_column(ratio=1)

    gpu_cells = []
    for i, g in enumerate(gpus):
        v_col = "magenta" if g["vram_pct"] < 75 else ("yellow" if g["vram_pct"] < 90 else "red")
        load_col = "green" if g["gpu_load_pct"] < 60 else ("yellow" if g["gpu_load_pct"] < 85 else "red")
        gpu_t = Text.from_markup(
            f"[bold magenta]Card:[/] AMD FirePro D500 [dim][{g['pci']}][/]\n"
            f"[bold magenta]Load:[/] {bar(g['gpu_load_pct'], 14, load_col)} [{load_col}]{g['gpu_load_pct']:5.1f}%[/]\n"
            f"[bold magenta]VRAM:[/] {bar(g['vram_pct'], 14, v_col)} [{v_col}]{g['vram_pct']:5.1f}%[/] [dim]({g['vram_used_mb']:.0f}M)[/]\n"
            f"[bold magenta]Core:[/] [bold cyan]{g['sclk_mhz']:.0f} MHz[/]  |  VRAM: [bold cyan]{g['mclk_mhz']:.0f} MHz[/]\n"
            f"[bold magenta]Temp:[/] [bold yellow]{g['temp_c']:.1f}°C[/]   |  Driver: [bold green]amdgpu/RADV[/]"
        )
        gpu_cells.append(Panel(gpu_t, title=f"[bold magenta]GPU {i}: FirePro D500 (Vulkan{i})[/]", box=box.ROUNDED))

    if len(gpu_cells) == 2:
        t_gpu.add_row(gpu_cells[0], gpu_cells[1])
    else:
        for c in gpu_cells:
            t_gpu.add_row(c)

    # 4. Inference Engine Section (Displays Active Benchmark, CLI Session, and Server)
    panels = []
    gen_tps = 0.0

    # Benchmark active
    if llama_procs["bench"]:
        b = llama_procs["bench"]
        bench_text = Text.from_markup(
            f"[bold yellow]⚡ ACTIVE SYNTHETIC BENCHMARK RUNNING[/]\n"
            f"[bold yellow]Tool:[/]     llama-bench [dim](PID: {b['pid']})[/]  |  [bold cyan]CPU:[/] {b['cpu_pct']:.1f}%  |  [bold cyan]Threads:[/] {b['threads']}\n"
            f"[bold yellow]Model:[/]    [bold white]{b['model']}[/]\n"
            f"[bold yellow]Offload:[/]  [bold magenta]{b['ngl']} layers[/] | Split: [bold green]{b['split']} ({b['ts']})[/] | Context: [white]{b['ctx']}[/]"
        )
        panels.append(Panel(bench_text, title="[bold yellow]● LLAMA-BENCH ACTIVE TEST[/]", box=box.ROUNDED, style="yellow"))

    # CLI Session active
    elif llama_procs["cli"]:
        c = llama_procs["cli"]
        cli_text = Text.from_markup(
            f"[bold yellow]⚡ ACTIVE INTERACTIVE INFERENCE RUNNING[/]\n"
            f"[bold yellow]Tool:[/]     llama-cli [dim](PID: {c['pid']})[/]  |  [bold cyan]CPU:[/] {c['cpu_pct']:.1f}%\n"
            f"[bold yellow]Model:[/]    [bold white]{c['model']}[/]\n"
            f"[bold yellow]Offload:[/]  [bold magenta]{c['ngl']} layers[/] | Split: [bold green]{c['split']} ({c['ts']})[/]"
        )
        panels.append(Panel(cli_text, title="[bold yellow]● LLAMA-CLI ACTIVE PROMPT[/]", box=box.ROUNDED, style="yellow"))

    # Server status
    if llama_procs["server"]:
        s = llama_procs["server"]
        metrics = s.get("server_metrics") or {}
        pred = metrics.get('llamacpp:tokens_predicted_total', '0')
        prompt_t = metrics.get('llamacpp:prompt_tokens_total', '0')
        proc_req = metrics.get('llamacpp:requests_processing', '0')
        gen_tps = float(metrics.get('llamacpp:predicted_tokens_seconds', '0') or 0)
        fa_badge = f" | FA: [bold green]{s['fa']}[/]" if s.get("fa") else ""

        if s.get("is_router") and not s.get("has_model"):
            offload_line = "[dim]Waiting for request (auto-loads optimal Mac Pro preset with --models-max 1)[/]"
        elif s["ngl"] == "0":
            offload_line = f"[bold magenta]0 layers (64 GB ECC Pure CPU)[/] | Threads: [bold green]{s['threads']}[/] | Context: [white]{s['ctx']} tokens[/]"
        elif s["ngl"] in ("24", "26"):
            offload_line = f"[bold magenta]{s['ngl']}/48 layers (Hybrid D500 + Xeon)[/] | Split: [bold green]{s['split']} ({s['ts']})[/]{fa_badge} | Ctx: [white]{s['ctx']}[/]"
        else:
            offload_line = f"[bold magenta]{s['ngl']} layers (Dual D500s)[/] | Split: [bold green]{s['split']} ({s['ts']})[/]{fa_badge} | Ctx: [white]{s['ctx']}[/]"

        speed_part = f"  |  Gen: [bold yellow]{gen_tps:.1f} tok/s[/]" if gen_tps > 0 else ""
        inf_t = Text.from_markup(
            f"[bold green]Process:[/]   llama-server [dim](PID: {s['pid']})[/]  |  [bold cyan]CPU:[/] {s['cpu_pct']:.1f}%  |  [bold cyan]RAM:[/] {s['mem_mb']:.0f} MB  |  [bold yellow]Port:[/] 8080 [dim](OpenAI API)[/]\n"
            f"[bold green]Model:[/]     [bold yellow]{s['model']}[/]\n"
            f"[bold green]Offload:[/]   {offload_line}\n"
            f"[bold green]API Stats:[/] Active Slots: [bold green]{proc_req}/{s['slots']}[/]  |  Tokens Gen: [bold yellow]{pred}[/]  |  Prompt: [bold cyan]{prompt_t}[/]{speed_part}"
        )
        panels.append(Panel(inf_t, title="[bold green]● OPENAI REST API SERVER [ONLINE][/]", box=box.ROUNDED, style="green"))

    if not panels:
        idle_t = Text.from_markup(
            "[dim]No active llama.cpp process currently running.[/dim]\n"
            "[bold white]Start server:[/] [cyan]~/serve.sh[/]\n"
            "[bold white]Run bench:[/]    [cyan]~/llama.cpp/build/bin/llama-bench -m ~/models/... -ngl 99 -sm layer -ts 1/1[/]"
        )
        panels.append(Panel(idle_t, title="[dim]○ LLAMA.CPP ENGINE [STANDBY / IDLE][/]", box=box.ROUNDED, style="dim"))

    # 5. Power & Efficiency Panel
    power_snap = power_monitor.sample() if power_monitor else None
    panels.append(_render_power_panel(power_snap, gen_tps=gen_tps))

    # 6. Footer
    api_port = os.environ.get("TRASHCAN_PORT", "8080")
    if llama_procs["server"]:
        api_port = llama_procs["server"].get("router_port") or llama_procs["server"].get("port") or api_port
    host_hint = os.environ.get("TRASHCAN_HOST", "0.0.0.0")
    footer = Text(
        f" [Ctrl+C] Exit Dashboard  │  Auto-Refreshing (1s)  │  Server: http://{host_hint}:{api_port} ",
        style="dim white on grey19",
    )

    return Group(header, t_sys, t_gpu, *panels, footer)


def run_power_probe():
    """Print raw RAPL and Apple SMC power keys for hardware verification."""
    pm = PowerMonitor(prime_sleep=0.3)
    snap = pm.sample(include_probe=True)
    console.print("[bold yellow]TrashCan-Top Power Telemetry Probe[/]")
    console.print(f"RAPL permission denied: {snap['rapl_denied']}  |  SMC permission denied: {snap['smc_denied']}")
    console.print(f"RAPL domains (W): {snap['rapl_watts']}")
    rows = snap.get("probe_rows", [])
    if rows:
        t = Table(title="Apple SMC 'P*' Keys")
        t.add_column("Key")
        t.add_column("Type")
        t.add_column("Raw Hex")
        t.add_column("Decoded")
        for r in rows:
            val_str = f"{r['value']:.2f}" if r["value"] is not None else "N/A"
            t.add_row(r["key"], r["type"], r["raw_hex"], val_str)
        console.print(t)
    elif snap["smc_denied"]:
        console.print("[yellow]Run with sudo (`sudo trash-top --probe-power`) to enumerate Apple SMC keys.[/]")


def main():
    global stop_gpu_threads
    parser = argparse.ArgumentParser(description="TrashCan-Top hardware and inference monitor")
    parser.add_argument(
        "--probe-power",
        action="store_true",
        help="Inspect raw Intel RAPL and Apple SMC power keys and exit",
    )
    args = parser.parse_args()
    if args.probe_power:
        run_power_probe()
        return

    start_gpu_threads()
    power_monitor = PowerMonitor()
    try:
        with Live(render_dashboard(power_monitor), refresh_per_second=1, screen=True) as live:
            while True:
                time.sleep(1.0)
                live.update(render_dashboard(power_monitor))
    except KeyboardInterrupt:
        stop_gpu_threads = True
        console.print("\n[dim]Trashcan-top closed.[/dim]")


if __name__ == "__main__":
    main()
