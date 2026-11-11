#!/usr/bin/env bash
# ==============================================================================
# OpenAI-Compatible Model Router Server Launcher for TrashCanAI (2013 Mac Pro)
# Provides /v1/chat/completions & /v1/models for trash-ai and IDE clients
# ==============================================================================

set -euo pipefail

BIN_DIR="${HOME}/llama.cpp/build/bin"
SERVER_BIN="${BIN_DIR}/llama-server"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_PRESET="${HOME}/.trashcan-models.ini"
if [ ! -f "${DEFAULT_PRESET}" ] && [ -f "${SCRIPT_DIR}/trashcan-models.ini" ]; then
    DEFAULT_PRESET="${SCRIPT_DIR}/trashcan-models.ini"
fi

if [ ! -f "${SERVER_BIN}" ]; then
    echo "[-] llama-server binary not found at ${SERVER_BIN}."
    echo "    Run ./scripts/restore-trashcan.sh (or ./scripts/remote-setup.sh) first to build llama.cpp."
    exit 1
fi

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"
MODELS_MAX="${MODELS_MAX:-1}"

if [ "${1:-}" = "--single" ] && [ -n "${2:-}" ]; then
    MODEL_FILE="$2"
    NGL="${NGL:-28}"
    SPLIT_MODE="${SPLIT_MODE:-layer}"
    TENSOR_SPLIT="${TENSOR_SPLIT:-1,1}"
    CTX_SIZE="${CTX_SIZE:-4096}"
    THREADS="${THREADS:-12}"

    if [ ! -f "${MODEL_FILE}" ]; then
        echo "[-] Model file not found: ${MODEL_FILE}"
        exit 1
    fi

    echo "======================================================================"
    echo "       Starting TrashCanAI Single-Model OpenAI Server                 "
    echo "======================================================================"
    echo " Model:         ${MODEL_FILE}"
    echo " Host/Port:     http://${HOST}:${PORT}"
    echo "======================================================================"

    exec "${SERVER_BIN}" \
        -m "${MODEL_FILE}" \
        --host "${HOST}" \
        --port "${PORT}" \
        -c "${CTX_SIZE}" \
        -np 1 \
        -ngl "${NGL}" \
        -sm "${SPLIT_MODE}" \
        -ts "${TENSOR_SPLIT}" \
        -fa on \
        -t "${THREADS}" \
        --metrics
fi

PRESET_FILE="${1:-${DEFAULT_PRESET}}"
if [ ! -f "${PRESET_FILE}" ]; then
    echo "[-] Preset file not found: ${PRESET_FILE}"
    exit 1
fi

# Resolve placeholder /home/YOUR_USER/models when launching directly from a repo checkout
if grep -q "/home/YOUR_USER/models" "${PRESET_FILE}"; then
    RESOLVED_PRESET="${HOME}/.trashcan-models.ini"
    sed "s|/home/YOUR_USER/models|${HOME}/models|g" "${PRESET_FILE}" > "${RESOLVED_PRESET}"
    PRESET_FILE="${RESOLVED_PRESET}"
fi

echo "======================================================================"
echo "     Starting TrashCanAI Optimized Model Router (2013 Mac Pro)        "
echo "======================================================================"
echo " Preset INI:    ${PRESET_FILE}"
echo " Max Loaded:    ${MODELS_MAX} (auto-swaps optimal VRAM/RAM setup)"
echo " Host/Port:     http://${HOST}:${PORT}"
echo "======================================================================"

exec "${SERVER_BIN}" \
    --models-preset "${PRESET_FILE}" \
    --models-max "${MODELS_MAX}" \
    --host "${HOST}" \
    --port "${PORT}" \
    --metrics

