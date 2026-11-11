#!/usr/bin/env bash
# ==============================================================================
# TrashCanAI: Complete Fresh Ubuntu Setup Script for 2013 Mac Pro (MacPro6,1)
# Configures a clean Ubuntu 24.04+ install to the verified TrashCanAI setup:
#   - Southern Islands (FirePro D500) amdgpu + Vulkan RADV kernel driver config
#   - Boot-time performance tuning (performance governor, DPM high, THP always,
#     minimum fan floor 1300 RPM via trashcan-performance.service)
#   - Ivy Bridge optimized llama.cpp Vulkan build (AVX + F16C, no AVX2/FMA)
#   - trash-top dashboard (with RAPL + Apple SMC power telemetry)
#   - trash-ai CLI helper & Model Router (~/.trashcan-models.ini + ~/serve.sh)
#   - Curated GGUF model downloads (1.5B, 3B, 7B, 14B, 32B + Moondream2 F16)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLAMA_REPO_URL="${LLAMA_REPO_URL:-https://github.com/ggerganov/llama.cpp.git}"
PINNED_LLAMA_COMMIT="0f35d6d7b"

MODEL_MODE="prompt"     # prompt | all | core | skip
PIN_LLAMA=0
ENABLE_SERVER_SERVICE=0
ASSUME_YES=0
NEEDS_REBOOT=0

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Sets up a fresh Ubuntu install on a 2013 Mac Pro (MacPro6,1) with amdgpu Vulkan,
Ivy Bridge llama.cpp, performance tuning, trash-top, trash-ai, and GGUF models.

Options:
  --all-models              Download all 7 GGUF models (~39 GB) non-interactively
  --core-models             Download core daily + vision models (~12 GB)
  --skip-models             Skip model downloads (useful if copying from backup)
  --pin-llama               Check out verified llama.cpp commit (${PINNED_LLAMA_COMMIT})
  --enable-server-service   Install/enable systemd unit to start port 8080 router on boot
  -y, --yes                 Run non-interactively without confirmation prompts
  -h, --help                Show this help message
EOF
}

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --all-models) MODEL_MODE="all" ;;
            --core-models) MODEL_MODE="core" ;;
            --skip-models) MODEL_MODE="skip" ;;
            --pin-llama) PIN_LLAMA=1 ;;
            --enable-server-service) ENABLE_SERVER_SERVICE=1 ;;
            -y|--yes) ASSUME_YES=1 ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                echo "[-] Unknown option: $1" >&2
                usage
                exit 1
                ;;
        esac
        shift
    done
}

verify_bundle() {
    local required=(
        "${SCRIPT_DIR}/dashboard.py"
        "${SCRIPT_DIR}/serve.sh"
        "${SCRIPT_DIR}/trash-ai"
        "${SCRIPT_DIR}/trashcan-models.ini"
        "${SCRIPT_DIR}/download-models.sh"
    )
    for f in "${required[@]}"; do
        if [ ! -f "$f" ]; then
            echo "[-] Missing required repo file: $f" >&2
            echo "    Run this script from inside the cloned trashAI repository." >&2
            exit 1
        fi
    done

    if [ "$(id -u)" -eq 0 ]; then
        echo "[-] Do not run directly as root (sudo will be invoked only where needed)." >&2
        echo "    Run as your regular sudo-capable user so llama.cpp, models, and configs live in \$HOME." >&2
        exit 1
    fi
}

inspect_hardware() {
    echo "[+] Checking CPU and GPU hardware..."
    CPU_MODEL=$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | xargs || echo "Unknown")
    echo "    CPU: ${CPU_MODEL}"
    if grep -q "avx2" /proc/cpuinfo; then
        HAS_AVX2=1
        echo "    AVX2: YES"
    else
        HAS_AVX2=0
        echo "    AVX2: NO (Ivy Bridge AVX + F16C target)"
    fi

    lspci -nnk | grep -EA3 "VGA|3D" || true
    CURRENT_DRIVER=$(lspci -nnk | grep -A3 "VGA" | awk -F': ' '/Kernel driver in use/{print $2; exit}' || echo "unknown")
    echo "    Active GPU driver: ${CURRENT_DRIVER}"
}

configure_amdgpu_kernel() {
    echo "[+] Configuring amdgpu Southern Islands support + groups..."
    local boot_changed=0

    if ! grep -q "amdgpu.si_support=1" /etc/default/grub || ! grep -q "radeon.si_support=0" /etc/default/grub; then
        sudo python3 - <<'PY'
import re
path = "/etc/default/grub"
with open(path, "r") as f:
    text = f.read()

def patch_line(m):
    val = m.group(1)
    for flag in ("radeon.si_support=0", "amdgpu.si_support=1"):
        if flag not in val.split():
            val = f"{flag} {val}".strip()
    return f'GRUB_CMDLINE_LINUX_DEFAULT="{val}"'

new_text, count = re.subn(r'^GRUB_CMDLINE_LINUX_DEFAULT="(.*)"$', patch_line, text, flags=re.M)
if count == 0:
    new_text = text.rstrip() + '\nGRUB_CMDLINE_LINUX_DEFAULT="radeon.si_support=0 amdgpu.si_support=1"\n'
with open(path, "w") as f:
    f.write(new_text)
PY
        boot_changed=1
    fi

    local desired_modprobe=$'options amdgpu si_support=1\noptions radeon si_support=0'
    local current_modprobe=""
    if [ -f /etc/modprobe.d/amdgpu.conf ]; then
        current_modprobe=$(cat /etc/modprobe.d/amdgpu.conf)
    fi
    if [ "${current_modprobe}" != "${desired_modprobe}" ]; then
        printf '%s\n' "${desired_modprobe}" | sudo tee /etc/modprobe.d/amdgpu.conf >/dev/null
        boot_changed=1
    fi

    if [ -f /etc/modprobe.d/blacklist-framebuffer.conf ]; then
        if ! grep -Eq '^\s*blacklist\s+radeonfb\b' /etc/modprobe.d/blacklist-framebuffer.conf; then
            echo "blacklist radeonfb" | sudo tee -a /etc/modprobe.d/blacklist-framebuffer.conf >/dev/null
            boot_changed=1
        fi
    else
        echo "blacklist radeonfb" | sudo tee /etc/modprobe.d/blacklist-framebuffer.conf >/dev/null
        boot_changed=1
    fi

    if [ "${boot_changed}" -eq 1 ]; then
        echo "[+] Updating GRUB and initramfs..."
        sudo update-grub
        sudo update-initramfs -u
    fi

    if [ "${CURRENT_DRIVER}" != "amdgpu" ]; then
        NEEDS_REBOOT=1
        echo "[!] 'amdgpu' is not yet active (currently '${CURRENT_DRIVER}'). Reboot after setup completes."
    fi

    sudo usermod -aG video,render "$USER" || true
}

install_packages() {
    echo "[+] Installing required Ubuntu packages and Vulkan/monitoring tools..."
    sudo apt-get update
    sudo apt-get install -y \
        build-essential cmake git pkg-config \
        curl wget openssh-server htop nvtop radeontop lm-sensors \
        vulkan-tools libvulkan-dev mesa-vulkan-drivers \
        glslc glslang-tools libshaderc-dev \
        libclblast-dev ocl-icd-opencl-dev \
        python3 python3-pip python3-venv python3-rich python3-psutil

    sudo systemctl enable --now ssh >/dev/null 2>&1 || true
}

install_performance_service() {
    echo "[+] Installing TrashCanAI performance tuning service (governor, DPM high, THP always, fan floor)..."
    sudo tee /usr/local/bin/trashcan-set-perf >/dev/null <<'EOF'
#!/usr/bin/env bash
for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    [ -e "$g" ] && echo performance > "$g" 2>/dev/null || true
done
for card in /sys/class/drm/card[0-9]; do
    [ -f "$card/device/vendor" ] || continue
    if [ "$(cat "$card/device/vendor" 2>/dev/null)" = "0x1002" ] && [ -f "$card/device/power_dpm_force_performance_level" ]; then
        echo high > "$card/device/power_dpm_force_performance_level" 2>/dev/null || true
    fi
done
echo always > /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null || true
echo always > /sys/kernel/mm/transparent_hugepage/defrag 2>/dev/null || true
[ -f /sys/devices/platform/applesmc.768/fan1_min ] && echo 1300 > /sys/devices/platform/applesmc.768/fan1_min 2>/dev/null || true
EOF
    sudo chmod 755 /usr/local/bin/trashcan-set-perf

    sudo tee /etc/systemd/system/trashcan-performance.service >/dev/null <<'EOF'
[Unit]
Description=TrashCan AI Performance Governor and DPM High Tuning
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/trashcan-set-perf
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable --now trashcan-performance.service
}

build_llama_cpp() {
    local llama_dir="${HOME}/llama.cpp"
    echo "[+] Preparing llama.cpp in ${llama_dir}..."

    if [ ! -d "${llama_dir}/.git" ]; then
        git clone "${LLAMA_REPO_URL}" "${llama_dir}"
    else
        git -C "${llama_dir}" fetch --all --tags
    fi

    if [ "${PIN_LLAMA}" -eq 1 ]; then
        echo "[+] Checking out verified commit ${PINNED_LLAMA_COMMIT}..."
        git -C "${llama_dir}" checkout "${PINNED_LLAMA_COMMIT}"
    else
        git -C "${llama_dir}" pull --ff-only || true
    fi

    local cmake_args=(
        -DGGML_VULKAN=ON
        -DCMAKE_BUILD_TYPE=Release
    )
    if [ "${HAS_AVX2}" -eq 0 ]; then
        cmake_args+=(
            -DGGML_AVX=ON
            -DGGML_AVX2=OFF
            -DGGML_FMA=OFF
            -DGGML_F16C=ON
        )
    fi

    cmake -S "${llama_dir}" -B "${llama_dir}/build" "${cmake_args[@]}"
    cmake --build "${llama_dir}/build" --config Release -j"$(nproc)"
}

install_user_tools() {
    echo "[+] Deploying trash-top, trash-ai, serve.sh router, and .trashcan-models.ini..."
    install -m 755 "${SCRIPT_DIR}/dashboard.py" "${HOME}/dashboard.py"
    sudo ln -sf "${HOME}/dashboard.py" /usr/local/bin/trash-top

    install -m 755 "${SCRIPT_DIR}/trash-ai" "${HOME}/trash-ai"
    sudo ln -sf "${HOME}/trash-ai" /usr/local/bin/trash-ai

    install -m 755 "${SCRIPT_DIR}/serve.sh" "${HOME}/serve.sh"

    sed -E "s|^((model|mmproj)[[:space:]]*=[[:space:]]*).*(/models/)|\1${HOME}\3|" \
        "${SCRIPT_DIR}/trashcan-models.ini" > "${HOME}/.trashcan-models.ini"
    mkdir -p "${HOME}/models"
}

install_optional_server_service() {
    if [ "${ENABLE_SERVER_SERVICE}" -ne 1 ]; then
        return 0
    fi

    echo "[+] Installing trashcan-llama.service (auto-start router on port 8080)..."
    sudo tee /etc/systemd/system/trashcan-llama.service >/dev/null <<EOF
[Unit]
Description=TrashCanAI OpenAI Model Router Server (port 8080)
After=network-online.target trashcan-performance.service
Wants=network-online.target

[Service]
Type=simple
User=${USER}
WorkingDirectory=${HOME}
ExecStart=${HOME}/serve.sh ${HOME}/.trashcan-models.ini
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable trashcan-llama.service
    if [ "${NEEDS_REBOOT}" -eq 0 ]; then
        sudo systemctl restart trashcan-llama.service
    fi
}

download_models() {
    case "${MODEL_MODE}" in
        all)
            "${SCRIPT_DIR}/download-models.sh" --all
            ;;
        core)
            "${SCRIPT_DIR}/download-models.sh" --core
            ;;
        skip)
            echo "[+] Skipping model downloads (--skip-models)."
            ;;
        prompt)
            if [ "${ASSUME_YES}" -eq 1 ]; then
                echo "[+] Non-interactive default: skipping ~39 GB model downloads (pass --all-models or --core-models to fetch)."
            else
                "${SCRIPT_DIR}/download-models.sh"
            fi
            ;;
    esac
}

print_summary() {
    echo ""
    echo "======================================================================"
    echo "               TrashCanAI Setup Complete                              "
    echo "======================================================================"
    if [ "${NEEDS_REBOOT}" -eq 1 ]; then
        echo "[!] REBOOT REQUIRED: Kernel parameters updated for amdgpu Vulkan."
        echo "    Run: sudo reboot"
        echo "    After reboot, verify dual GPUs with: vulkaninfo --summary"
    else
        echo "[+] Active Vulkan GPUs:"
        vulkaninfo --summary 2>/dev/null | grep -E "deviceName|driverName|driverInfo" || echo "    Run vulkaninfo --summary to inspect."
    fi
    echo "[+] llama-server version:"
    "${HOME}/llama.cpp/build/bin/llama-server" --version 2>&1 | head -n 3 || true
    echo ""
    echo "Daily commands:"
    echo "  Start OpenAI router:   ~/serve.sh"
    echo "  Live power/GPU HUD:    sudo trash-top"
    echo "  Local/LAN CLI test:    TRASH_AI_HOST=<macpro-ip> trash-ai status"
    echo "======================================================================"
}

main() {
    parse_args "$@"
    verify_bundle
    inspect_hardware
    configure_amdgpu_kernel
    install_packages
    install_performance_service
    build_llama_cpp
    install_user_tools
    install_optional_server_service
    download_models
    print_summary
}

main "$@"
