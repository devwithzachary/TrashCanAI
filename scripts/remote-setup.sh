#!/usr/bin/env bash
# ==============================================================================
# TrashCanAI: Minimal Driver + llama.cpp Setup Script for 2013 Mac Pro (MacPro6,1)
# For full one-command setup including systemd tuning, trash-top, serve.sh,
# trash-ai, and GGUF models, see scripts/restore-trashcan.sh.
# ==============================================================================

set -euo pipefail

echo "======================================================================"
echo "          TrashCanAI: 2013 Mac Pro Driver & Compiler Setup            "
echo "======================================================================"

# 1. Hardware Inspection
echo "[+] Checking CPU capabilities..."
CPU_MODEL=$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | xargs)
echo "    CPU Detected: $CPU_MODEL"
if grep -q "avx2" /proc/cpuinfo; then
    echo "    AVX2 Support: YES"
    HAS_AVX2=1
else
    echo "    AVX2 Support: NO (Ivy Bridge detected - custom compile required)"
    HAS_AVX2=0
fi

echo "[+] Checking GPU hardware..."
lspci -nnk | grep -EA3 "VGA|3D" || true

CURRENT_DRIVER=$(lspci -nnk | grep -A2 "VGA" | grep "Kernel driver in use" | head -n1 | awk '{print $5}' || echo "unknown")
echo "    Current Kernel Driver: $CURRENT_DRIVER"

# 2. Kernel Parameter Configuration for amdgpu
if [ "$CURRENT_DRIVER" != "amdgpu" ]; then
    echo ""
    echo "[!] GPUs are currently running on '$CURRENT_DRIVER', not 'amdgpu'."
    echo "[!] Southern Islands (GCN 1.0 / Tahiti) requires enabling amdgpu.si_support=1."
    read -p "    Do you want to apply the kernel parameters and reboot? [y/N]: " -r APPLY_KERNEL
    if [[ "$APPLY_KERNEL" =~ ^[Yy]$ ]]; then
        echo "[+] Updating /etc/default/grub..."
        if ! grep -q "amdgpu.si_support=1" /etc/default/grub; then
            sudo sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT="/GRUB_CMDLINE_LINUX_DEFAULT="radeon.si_support=0 amdgpu.si_support=1 /' /etc/default/grub
        fi

        echo "[+] Creating /etc/modprobe.d/amdgpu.conf..."
        sudo tee /etc/modprobe.d/amdgpu.conf > /dev/null <<EOF
options amdgpu si_support=1
options radeon si_support=0
EOF

        echo "[+] Updating GRUB and initramfs..."
        sudo update-grub
        sudo update-initramfs -u

        echo "[+] Done. System must be rebooted to take effect."
        read -p "    Reboot now? [y/N]: " -r REBOOT_NOW
        if [[ "$REBOOT_NOW" =~ ^[Yy]$ ]]; then
            sudo reboot
        else
            echo "Please reboot manually and re-run this script."
            exit 0
        fi
    else
        echo "Skipping kernel modification. Note: Vulkan will not work under legacy 'radeon' driver."
    fi
fi

# 3. System Dependencies
echo ""
echo "[+] Installing system dependencies and Mesa Vulkan drivers..."
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
    curl \
    wget \
    htop \
    nvtop \
    radeontop \
    python3 \
    python3-pip \
    python3-rich \
    python3-psutil

# 4. Vulkan Verification
echo ""
echo "[+] Verifying Vulkan installation..."
if command -v vulkaninfo >/dev/null 2>&1; then
    vulkaninfo --summary || true
else
    echo "[-] vulkaninfo not found or failed."
fi

# 5. Build llama.cpp
echo ""
LLAMA_DIR="$HOME/llama.cpp"
if [ ! -d "$LLAMA_DIR" ]; then
    echo "[+] Cloning llama.cpp into $LLAMA_DIR..."
    git clone https://github.com/ggerganov/llama.cpp.git "$LLAMA_DIR"
else
    echo "[+] Updating llama.cpp in $LLAMA_DIR..."
    cd "$LLAMA_DIR" && git pull
fi

cd "$LLAMA_DIR"
mkdir -p build && cd build

echo "[+] Configuring CMake for Ivy Bridge AVX + Vulkan Dual-GPU..."
if [ "$HAS_AVX2" -eq 0 ]; then
    cmake .. \
        -DGGML_VULKAN=ON \
        -DGGML_AVX=ON \
        -DGGML_AVX2=OFF \
        -DGGML_FMA=OFF \
        -DGGML_F16C=ON \
        -DCMAKE_BUILD_TYPE=Release
else
    cmake .. \
        -DGGML_VULKAN=ON \
        -DCMAKE_BUILD_TYPE=Release
fi

echo "[+] Compiling llama.cpp using $(nproc) cores..."
cmake --build . --config Release -j"$(nproc)"

echo ""
echo "======================================================================"
echo "[✓] Build complete! Executables available in: $LLAMA_DIR/build/bin/"
echo "======================================================================"
"$LLAMA_DIR/build/bin/llama-cli" --version || true

