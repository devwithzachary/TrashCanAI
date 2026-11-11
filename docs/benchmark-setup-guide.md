# Benchmark Environment & Fairness Setup Guide

To ensure benchmark numbers are reproducible and scientifically fair across heterogeneous hardware architectures, all test machines use controlled OS power settings and the exact same quantized `.gguf` weights.

---

## The 6 Rules of Benchmark Fairness

1. **Exact Same GGUF Files**: Run the identical `.gguf` files across all machines.
2. **Identical Engine & Git Commit**: Pin the same release or git commit of `llama.cpp` (`0f35d6d7b`).
3. **Identical Context Window**: Fixed context size (`-c 4096`).
4. **AC Power & Performance Governors**: Connect laptops to wall power and disable low-power throttling.
5. **Thermal Consistency (Warm-up + Steady State)**: 1 unrecorded warm-up run followed by 3 timed test runs (`-r 3`).
6. **Two-Tier Measurement (Hardware-Accelerated vs. Pure CPU)**:
   * **Tier 1 (Native Best GPU/Accelerator)**: Vulkan on Mac Pro & x86 iGPUs (`-DGGML_VULKAN=ON`), Metal on Apple Silicon (`-DGGML_METAL=ON`).
   * **Tier 2 (Pure CPU `-ngl 0`)**: Isolates CPU IPC, cache hierarchy, and DRAM bandwidth.

---

## Platform Notes

### 1. 2013 Mac Pro (Ubuntu Server 24.04 LTS)
* Verify `amdgpu` active via `lspci -nnk | grep -EA3 "VGA|3D"`.
* Enable `trashcan-performance.service` (CPU `performance`, GPU DPM `high`, THP `always`).
* Compile `llama.cpp` with `-DGGML_VULKAN=ON -DGGML_AVX=ON -DGGML_AVX2=OFF -DGGML_FMA=OFF -DGGML_F16C=ON -DCMAKE_BUILD_TYPE=Release`.
* Use forward slash `-ts 1/1` in `llama-bench` (commas in `llama-bench` act as parameter sweep separators).

### 2. Modern x86 Laptop (Core Ultra 5 125H / Intel Arc iGPU, CachyOS Linux)
* Compile `llama.cpp` at commit `0f35d6d7b` with `-DGGML_VULKAN=ON -DGGML_NATIVE=ON -DGGML_LTO=ON`.
* **Crucial UMA note**: For Pure CPU runs (`-ngl 0`), pass `-dev none --no-host 1` so weights allocate in cached host DRAM instead of uncached GPU shared buffers (`anon_inode:i915.gem`).

### 3. Portable Apple Silicon (`MacBook Neo` / A18 Pro, 8 GB Unified Memory)
* Compile with `-DGGML_METAL=ON -DGGML_LTO=ON` at commit `0f35d6d7b`. Run on AC power under `caffeinate -dimsu`.
* For 6-core `2P+4E` CPU-only runs without SMT, keep `-t <= 6` (use `-t 2` for P-cores only or `-t 6` physical cores).

### 4. Apple M4 Max Studio (36 GB Unified Memory, 410 GB/s)
* Compile with `-DGGML_METAL=ON -DGGML_LTO=ON` at commit `0f35d6d7b`.
* For `10P+4E` Pure CPU runs, pass `-dev none` and `-t 8` or `-t 10` (P-cores only).

---

## Standardized `llama-bench` Commands

### Accelerated GPU Run
```bash
./build/bin/llama-bench \
    -m /path/to/qwen2.5-coder-1.5b-instruct-q8_0.gguf \
    -n 128 -p 512 -ngl 99 -fa 1 -r 3 -o md
```
*(On the Mac Pro, add `-sm layer -ts 1/1 -t 12` for dual-GPU layer split.)*

### Pure CPU Baseline Run
```bash
./build/bin/llama-bench \
    -m /path/to/qwen2.5-coder-1.5b-instruct-q8_0.gguf \
    -n 128 -p 512 -ngl 0 -t 8 -r 3 -o md
```
