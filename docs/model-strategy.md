# Model Selection & Tier Strategy for the 2013 Mac Pro

To extract maximum performance from the Mac Pro's hardware profile (Dual 3 GB FirePro D500 GPUs + 64 GB Quad-Channel DDR3 RAM + 12-Core Xeon), workloads are divided into three distinct tiers matching [`scripts/trashcan-models.ini`](../scripts/trashcan-models.ini).

---

## Tier Summary Matrix

| Tier | Target Workload | Model Examples | Quantization | Memory Target | Measured Speed |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Tier 1: Dual-GPU Resident** | Spell check, grammar, social tags, alt-text, fast edits | Qwen 2.5 Coder 1.5B, Qwen 2.5 3B, Moondream2 | Q8_0 / Q4_K_M / F16 | 100% VRAM (~4–5 GB across dual D500s) | **22 – 37+ tok/s** |
| **Tier 2: Hybrid / Full 7B VRAM** | Day-to-day Android (Kotlin/Compose), Linux scripting | Qwen 2.5 Coder 7B | Q4_K_M | Dual D500 28/28 layers + Flash Attention | **~13.0 tok/s** |
| **Tier 3: Heavy RAM Workhorse** | Large multi-file refactoring, deep architecture | Qwen 2.5 Coder 14B / 32B | Q4_K_M | Hybrid 24/48L (14B) or Pure 64 GB DDR3 RAM (32B) | **2.5 – 6.4 tok/s** |

---

## Tier 1: Dual-GPU Resident (Interactive & Instant)
* **Hardware path**: 100% VRAM offload across both FirePro D500s (`--split-mode layer --tensor-split 1,1 -ngl 99 -fa on`).
* **Why it shines**: Dual D500 GDDR5 (~240 GB/s per card) bypasses system DDR3 entirely.

### Recommended Models:
1. **Qwen 2.5 Coder 1.5B-Instruct** (`qwen2.5-coder-1.5b-instruct-q8_0.gguf` ~1.8 GB) — *Preset: `trash-fast`*
2. **Qwen 2.5 3B-Instruct** (`qwen2.5-3b-instruct-q4_k_m.gguf` ~2.0 GB) — *Preset: `trash-social`*
3. **Moondream2** (`moondream2-text-model-f16.gguf` + `moondream2-mmproj-f16.gguf`, Vicuna chat template) — *Preset: `trash-vision`*

---

## Tier 2: The Daily Coder (7B on Dual D500s)
* **Hardware path**: With `-fa on`, Qwen 2.5 Coder 7B fits all 28/28 transformer layers across the dual 3 GB cards (`-ngl 28 --split-mode layer --tensor-split 1,1`), yielding **~74.4 tok/s prompt prefill / ~13.0 tok/s generation**.
* **Preset**: `trash-code` (loaded on startup in [`scripts/trashcan-models.ini`](../scripts/trashcan-models.ini)).

---

## Tier 3: 64 GB Quad-Channel RAM Heavyweight (14B & 32B)
* **Why it shines**: Modern 8 GB laptops OOM completely on 14B and 32B models. The Mac Pro's 64 GB Quad-Channel ECC DDR3 handles them reliably, especially with Linux Transparent Huge Pages (`always`) enabled and physical core count `-t 12` (avoiding hyperthread cache contention).
* **14B Hybrid (`trash-deep`)**: 24/48 layers on dual D500s + Xeon CPU reaches **27.6 tok/s prefill / 6.40 tok/s generation**.
* **32B Pure CPU (`trash-heavy`)**: Pure CPU (`-ngl 0 -t 12`) avoids PCIe activation bounce overhead and runs steadily in quad-channel ECC RAM (**9.06 tok/s prefill / 2.53 tok/s generation**).

