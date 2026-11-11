# TrashAI: Reviving the 2013 Mac Pro ("Trash Can") as a Local AI Node

Turning an inexpensive 2013 Apple Mac Pro (`MacPro6,1`, dual FirePro D500 / 64 GB ECC DDR3) into an optimized, OpenAI-compatible local AI server, monitoring dashboard (`trash-top`), CLI workflow (`trash-ai`), and IDE coding assistant on Ubuntu Server.

---

## Hardware Architecture
* **System**: Apple Mac Pro Late 2013 (`MacPro6,1`)
* **CPU**: 12-Core / 24-Thread Intel Xeon E5-2697 v2 @ 2.7 GHz (Ivy Bridge-EP, 130 W TDP, 30 MB L3)
* **System RAM**: 64 GB Quad-Channel DDR3-1866 ECC (~45–55 GB/s sustained bandwidth)
* **GPUs**: Dual AMD FirePro D500 (Tahiti, GCN 1.0 / Southern Islands, 3 GB GDDR5 each = 6 GB total VRAM, ~240 GB/s per GPU)
* **Host OS**: Ubuntu Server (`24.04 LTS`+)

---

## Why Stock Tools Fail (And How This Setup Fixes It)

1. **No ROCm on GCN 1.0**: ROCm dropped Southern Islands (`gfx600`) years ago. Instead of ROCm, enabling Mesa's open-source **`RADV` Vulkan** driver provides full dual-GPU compute acceleration.
2. **Legacy `radeon` Kernel Driver Default**: Ubuntu binds Tahiti/GCN 1.0 GPUs to `radeon` by default, which has zero Vulkan support. Switching GRUB/modprobe to **`amdgpu.si_support=1 radeon.si_support=0`** unlocks dual-GPU Vulkan 1.3.
3. **Ivy Bridge `AVX2` Trap (`SIGILL`)**: The E5-2697 v2 supports **`AVX` + `F16C`** but **not** `AVX2` or `FMA3`. Prebuilt x86-64-v3 binaries crash with `Illegal instruction (core dumped)`. Compiling `llama.cpp` with explicit Ivy Bridge + Vulkan flags resolves this completely.
4. **System Performance Bottlenecks**: Setting CPU cores to `performance`, forcing AMD DPM `high`, enabling Linux **Transparent Huge Pages (`always`)** (which alone lifted Pure CPU 14B generation by +60%), and setting a `1300 RPM` fan floor (`applesmc`) keep sustained performance deterministic.

---

## Quick Start (Fresh Ubuntu 24.04+)

Clone this repository on your 2013 Mac Pro and run the all-in-one restore script as your regular `sudo`-capable user (not as `root`):

```bash
git clone https://github.com/devwithzachary/TrashCanAI.git ~/TrashCanAI
cd ~/TrashCanAI
./scripts/restore-trashcan.sh --all-models --pin-llama
sudo reboot
```

Options:
* `--all-models`: Download all 7 curated GGUF models (~39 GB total)
* `--core-models`: Download core 1.5B, 3B, 7B, and Moondream2 Vision weights (~12 GB)
* `--skip-models`: Skip model downloads
* `--pin-llama`: Pin `llama.cpp` to verified commit `0f35d6d7b`
* `--enable-server-service`: Install/enable a boot-time systemd service for port `8080`

---

## Included Tools & Workflows

### 1. Model Router Server ([`scripts/serve.sh`](scripts/serve.sh) & [`scripts/trashcan-models.ini`](scripts/trashcan-models.ini))
Runs `llama-server --models-preset ~/.trashcan-models.ini --models-max 1` on port `8080`, automatically loading and swapping each task's tuned GPU/CPU split:

| Preset Name | Model | Hardware Strategy | Speed (`pp512 / tg128`) |
| :--- | :--- | :--- | :--- |
| `trash-fast` | Qwen 2.5 Coder 1.5B (`Q8_0`) | 100% Dual D500 Vulkan + FA | **392.5 / 36.6 tok/s** |
| `trash-social` | Qwen 2.5 3B (`Q4_K_M`) | 100% Dual D500 Vulkan + FA | **178.3 / 22.1 tok/s** |
| `trash-code` | Qwen 2.5 Coder 7B (`Q4_K_M`) | 100% Dual D500 28/28L + FA | **74.4 / 13.0 tok/s** |
| `trash-deep` | Qwen 2.5 Coder 14B (`Q4_K_M`) | Hybrid 24L Dual D500 + Xeon THP | **27.6 / 6.40 tok/s** |
| `trash-heavy` | Qwen 2.5 Coder 32B (`Q4_K_M`) | 64 GB ECC Pure CPU (`-ngl 0 -t 12` THP) | **9.06 / 2.53 tok/s** |
| `trash-vision` | Moondream2 (`F16` + `mmproj`) | Dual D500 Vulkan + Vicuna template | **1.75s ViT** (~7.8s total) |

Start on the Mac Pro:
```bash
~/serve.sh
```

### 2. Live Telemetry HUD (`trash-top` / [`scripts/dashboard.py`](scripts/dashboard.py))
Monitors Xeon cores, 64 GB DDR3, dual FirePro D500 load/VRAM/clocks (`radeontop`), loaded router model/slot `/metrics`, and **live hardware wattage + efficiency (`tok/s/W`, `J/tok`)** via **Intel RAPL** and **Apple SMC** (`sudo` required by Linux sysfs):
```bash
sudo trash-top
# Optional raw rail inspection:
sudo trash-top --probe-power
```

### 3. CLI Task Helper (`trash-ai` / [`scripts/trash-ai`](scripts/trash-ai))
Zero-dependency Python CLI routing everyday tasks cleanly to your Mac Pro router:
```bash
export TRASH_AI_HOST=<mac-pro-ip>

trash-ai status
trash-ai spellcheck "their are too many cable on teh desk"
trash-ai hashtag --caption "Reviving a 2013 Mac Pro for local AI"
trash-ai code --file src/Main.kt --lines 10-65 "Review this Compose layout"
trash-ai alt-text --html screenshot.jpg
```
*(Optional: set `TRASH_AI_SSH_TARGET=user@<mac-pro-ip>` to let `trash-ai` auto-start `llama-server` over SSH if it isn't running yet.)*

---

## Documentation
* [`docs/hardware-and-driver-setup.md`](docs/hardware-and-driver-setup.md): Step-by-step `amdgpu` GRUB/modprobe, Vulkan `RADV`, and Ivy Bridge `llama.cpp` manual setup.
* [`docs/model-strategy.md`](docs/model-strategy.md): 3-Tier model selection strategy across Dual 3 GB VRAM and 64 GB DDR3 RAM.
* [`docs/benchmarks.md`](docs/benchmarks.md): Standardized speed, multimodal vision, and power-efficiency measurements.
* [`docs/benchmark-setup-guide.md`](docs/benchmark-setup-guide.md): Reproducible multi-platform benchmarking methodology.
* [`docs/android-studio-setup.md`](docs/android-studio-setup.md): Connecting Android Studio / JetBrains IDEs over LAN.

