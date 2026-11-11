#!/usr/bin/env bash
# ==============================================================================
# Helper script to download all curated GGUF models for TrashCanAI (MacPro6,1)
# Matches the verified preset table in scripts/trashcan-models.ini
# Usage: ./download-models.sh [--all | --core | --help]
# ==============================================================================

set -euo pipefail

MODEL_DIR="${MODEL_DIR:-${HOME}/models}"

URL_1_5B="https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-1.5b-instruct-q8_0.gguf"
URL_3B="https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf"
URL_7B="https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf"
URL_14B="https://huggingface.co/Qwen/Qwen2.5-Coder-14B-Instruct-GGUF/resolve/main/qwen2.5-coder-14b-instruct-q4_k_m.gguf"
URL_32B="https://huggingface.co/Qwen/Qwen2.5-Coder-32B-Instruct-GGUF/resolve/main/qwen2.5-coder-32b-instruct-q4_k_m.gguf"
URL_MD2_TXT="https://huggingface.co/moondream/moondream2-gguf/resolve/main/moondream2-text-model-f16.gguf"
URL_MD2_PROJ="https://huggingface.co/moondream/moondream2-gguf/resolve/main/moondream2-mmproj-f16.gguf"

download_hf() {
    local url="$1"
    local filename="$2"
    mkdir -p "${MODEL_DIR}"
    local dest="${MODEL_DIR}/${filename}"

    if [ -f "${dest}" ]; then
        local remote_len local_len
        remote_len=$(curl -fsIL "${url}" 2>/dev/null | awk 'tolower($1)=="content-length:" {val=$2} END {gsub(/\r/,"",val); print val}' || true)
        local_len=$(wc -c < "${dest}")
        if [ -n "${remote_len}" ] && [ "${local_len}" = "${remote_len}" ]; then
            echo "[✓] Already complete: ${filename}"
            return 0
        fi
    fi

    echo "[+] Downloading ${filename}..."
    curl -fL --progress-bar -C - "${url}" -o "${dest}"
}

download_core() {
    download_hf "${URL_1_5B}" "qwen2.5-coder-1.5b-instruct-q8_0.gguf"
    download_hf "${URL_3B}" "qwen2.5-3b-instruct-q4_k_m.gguf"
    download_hf "${URL_7B}" "qwen2.5-coder-7b-instruct-q4_k_m.gguf"
    download_hf "${URL_MD2_TXT}" "moondream2-text-model-f16.gguf"
    download_hf "${URL_MD2_PROJ}" "moondream2-mmproj-f16.gguf"
}

download_all() {
    download_core
    download_hf "${URL_14B}" "qwen2.5-coder-14b-instruct-q4_k_m.gguf"
    download_hf "${URL_32B}" "qwen2.5-coder-32b-instruct-q4_k_m.gguf"
}

MODE="${1:-}"
case "${MODE}" in
    --all)
        download_all
        echo "[✓] All 7 models ready in ${MODEL_DIR}"
        exit 0
        ;;
    --core)
        download_core
        echo "[✓] Core models ready in ${MODEL_DIR}"
        exit 0
        ;;
    --help|-h)
        echo "Usage: $0 [--all | --core | --help]"
        exit 0
        ;;
    "")
        ;;
    *)
        echo "[-] Unknown option: ${MODE}" >&2
        exit 1
        ;;
esac

echo "[+] Target model directory: ${MODEL_DIR}"
echo ""
echo "Select models to download:"
echo "1) Tier 1: Qwen 2.5 Coder 1.5B Instruct (Q8_0 ~1.8 GB) [trash-fast]"
echo "2) Tier 1: Qwen 2.5 3B Instruct (Q4_K_M ~2.0 GB) [trash-social]"
echo "3) Tier 2: Qwen 2.5 Coder 7B Instruct (Q4_K_M ~4.4 GB) [trash-code]"
echo "4) Tier 3: Qwen 2.5 Coder 14B Instruct (Q4_K_M ~8.4 GB) [trash-deep]"
echo "5) Tier 3: Qwen 2.5 Coder 32B Instruct (Q4_K_M ~19 GB) [trash-heavy]"
echo "6) Vision: Moondream2 F16 + mmproj (~3.6 GB total) [trash-vision]"
echo "7) Core Preset Bundle (1.5B, 3B, 7B, Moondream2 ~12 GB)"
echo "8) All 7 TrashCanAI Models (~39 GB total - complete setup)"
read -p "Enter choice [1-8]: " CHOICE

case "${CHOICE}" in
    1) download_hf "${URL_1_5B}" "qwen2.5-coder-1.5b-instruct-q8_0.gguf" ;;
    2) download_hf "${URL_3B}" "qwen2.5-3b-instruct-q4_k_m.gguf" ;;
    3) download_hf "${URL_7B}" "qwen2.5-coder-7b-instruct-q4_k_m.gguf" ;;
    4) download_hf "${URL_14B}" "qwen2.5-coder-14b-instruct-q4_k_m.gguf" ;;
    5) download_hf "${URL_32B}" "qwen2.5-coder-32b-instruct-q4_k_m.gguf" ;;
    6)
        download_hf "${URL_MD2_TXT}" "moondream2-text-model-f16.gguf"
        download_hf "${URL_MD2_PROJ}" "moondream2-mmproj-f16.gguf"
        ;;
    7) download_core ;;
    8) download_all ;;
    *)
        echo "[-] Invalid choice."
        exit 1
        ;;
esac

echo "[✓] Download complete. Models saved to ${MODEL_DIR}"

