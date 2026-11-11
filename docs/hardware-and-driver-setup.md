# Hardware & Driver Setup Guide: Dual FirePro D500 on Ubuntu Server

This guide details the manual steps required to unlock Vulkan compute on AMD FirePro D500 GPUs (GCN 1.0 / Southern Islands / Tahiti) and compile an optimized inference engine that avoids Ivy Bridge `Illegal instruction` crashes. *(For automated provisioning, use [`scripts/restore-trashcan.sh`](../scripts/restore-trashcan.sh).)*

---

## Step 1: Switch from Legacy `radeon` to Modern `amdgpu` Kernel Driver

By default, the Linux kernel binds GCN 1.0 (Southern Islands) hardware to the legacy `radeon` driver, which lacks Vulkan support. Configure the kernel to bind Tahiti GPUs to `amdgpu` instead.

### 1.1 Edit GRUB Defaults
Edit `/etc/default/grub`:
```bash
sudo nano /etc/default/grub
```

Find `GRUB_CMDLINE_LINUX_DEFAULT` and add `radeon.si_support=0 amdgpu.si_support=1`:
```bash
GRUB_CMDLINE_LINUX_DEFAULT="radeon.si_support=0 amdgpu.si_support=1"
```

Create `/etc/modprobe.d/amdgpu.conf` so modules load with the same flags inside initramfs:
```bash
sudo tee /etc/modprobe.d/amdgpu.conf > /dev/null <<EOF
options amdgpu si_support=1
options radeon si_support=0
EOF
```

Add your user to the `video` and `render` groups:
```bash
sudo usermod -aG video,render "$USER"
```

### 1.2 Update Bootloader and Reboot
```bash
sudo update-grub
sudo update-initramfs -u
sudo reboot
```

---

## Step 2: Verify GPU Driver and Vulkan Support

After rebooting, verify `amdgpu` and Mesa RADV Vulkan.

### 2.1 Check Kernel Driver in Use
```bash
lspci -nnk | grep -EA3 "VGA|3D"
```
Both AMD FirePro D500 cards should display:
```text
Kernel driver in use: amdgpu
Kernel modules: radeon, amdgpu
```

### 2.2 Install Mesa Vulkan, Monitoring Tools, and Build Essentials
```bash
sudo apt update
sudo apt install -y \
    build-essential \
    cmake \
    git \
    pkg-config \
    vulkan-tools \
    libvulkan-dev \
    mesa-vulkan-drivers \
    glslc \
    glslang-tools \
    libshaderc-dev \
    libclblast-dev \
    ocl-icd-opencl-dev \
    radeontop \
    python3-rich \
    python3-psutil \
    htop \
    nvtop
```

### 2.3 Verify Vulkan Detection
```bash
vulkaninfo --summary
```
Verify that **two Vulkan discrete devices** (`RADV TAHITI`) are reported with Vulkan 1.3 support.

---

## Step 3: Compiling `llama.cpp` for Ivy Bridge + Vulkan

### 3.1 The Ivy Bridge Instruction Trap
The Intel Xeon E5-2697 v2 is based on Ivy Bridge:
* **Supported**: SSE4.1, SSE4.2, AVX, F16C.
* **Not Supported**: AVX2, FMA3, AVX-512.

Prebuilt x86-64-v3 binaries crash immediately with:
```text
Illegal instruction (core dumped)
```

### 3.2 Building from Source
```bash
cd ~
git clone https://github.com/ggerganov/llama.cpp.git
cd llama.cpp
mkdir build && cd build

cmake .. \
    -DGGML_VULKAN=ON \
    -DGGML_AVX=ON \
    -DGGML_AVX2=OFF \
    -DGGML_FMA=OFF \
    -DGGML_F16C=ON \
    -DCMAKE_BUILD_TYPE=Release

cmake --build . --config Release -j"$(nproc)"
```

### 3.3 Boot-Time Performance Tuning
To keep clocks, Transparent Huge Pages (THP), and cooling deterministic across reboots:
* CPU governor: `performance`
* AMD GPU DPM level: `high` (`/sys/class/drm/card*/device/power_dpm_force_performance_level`)
* Transparent Huge Pages: `/sys/kernel/mm/transparent_hugepage/enabled` = `always` and `defrag` = `always` (+60% Pure CPU throughput on 14B)
* Apple SMC cooling baseline: `/sys/devices/platform/applesmc.768/fan1_min` = `1300`

[`scripts/restore-trashcan.sh`](../scripts/restore-trashcan.sh) installs `/usr/local/bin/trashcan-set-perf` and `trashcan-performance.service` automatically.

### 3.4 Verify Multi-GPU Vulkan Execution
```bash
~/llama.cpp/build/bin/llama-cli \
    -m ~/models/qwen2.5-coder-1.5b-instruct-q8_0.gguf \
    -p "Hello, world!" \
    -ngl 99 \
    --split-mode layer \
    --tensor-split 1,1
```
Look for two Vulkan devices (`AMD RADV TAHITI`) in startup logs.

