# Benchmark Results & Efficiency Comparison

Standardized performance, multimodal vision, and speed-vs-power comparisons between the revived **2013 Mac Pro (`MacPro6,1`)** and three modern systems using identical quantized `.gguf` weights and `llama.cpp` commit `0f35d6d7b`.

See [`docs/benchmark-setup-guide.md`](benchmark-setup-guide.md) for OS tuning and compilation methodology.

---

## Hardware Comparison Profiles

| Spec / Machine | **Apple Mac Pro (2013)** | **Modern x86 Laptop (Core Ultra 5)** | **Entry Apple Silicon Laptop (A18 Pro)** | **M4 Max Mac Studio** |
| :--- | :--- | :--- | :--- | :--- |
| **OS** | Ubuntu Server 24.04 LTS | CachyOS Linux | macOS 27.2 | macOS 27.0.1 |
| **CPU** | 12C/24T Xeon E5-2697 v2 | Core Ultra 5 125H (14C/18T) | Apple A18 Pro (6C: 2P+4E) | Apple M4 Max (14C: 10P+4E) |
| **GPU** | Dual FirePro D500 (3 GB + 3 GB) | Intel Arc iGPU (23.2 GiB UMA) | 5-Core GPU (5.33 GiB Metal cap) | 32-Core GPU (28.08 GiB Metal cap) |
| **Memory** | 64 GB Quad-Ch DDR3 ECC | 32 GB (30 GiB) LPDDR5/X | 8 GB Unified | 36 GB Unified (410 GB/s) |
| **Backend** | `llama.cpp` (Vulkan dual-GPU + AVX) | `llama.cpp` (Vulkan ANV) | `llama.cpp` (Metal) | `llama.cpp` (Metal) |

---

## Models Tested

| Model | File Name | HuggingFace Source | Size (On Disk) |
| :--- | :--- | :--- | :--- |
| **Qwen 2.5 Coder 1.5B** | `qwen2.5-coder-1.5b-instruct-q8_0.gguf` | `Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF` | ~1.89 GB |
| **Qwen 2.5 3B** | `qwen2.5-3b-instruct-q4_k_m.gguf` | `Qwen/Qwen2.5-3B-Instruct-GGUF` | ~2.10 GB |
| **Qwen 2.5 Coder 7B** | `qwen2.5-coder-7b-instruct-q4_k_m.gguf` | `Qwen/Qwen2.5-Coder-7B-Instruct-GGUF` | ~4.68 GB |
| **Qwen 2.5 Coder 14B**| `qwen2.5-coder-14b-instruct-q4_k_m.gguf` | `Qwen/Qwen2.5-Coder-14B-Instruct-GGUF` | ~8.99 GB |
| **Qwen 2.5 Coder 32B**| `qwen2.5-coder-32b-instruct-q4_k_m.gguf` | `Qwen/Qwen2.5-Coder-32B-Instruct-GGUF` | ~19.85 GB |
| **Moondream2 Vision** | `moondream2-text-model-f16.gguf` + `mmproj` | `moondream/moondream2-gguf` | ~3.75 GB combined |

*Protocol: `-c 4096`, `-p 512`, `-n 128`, 1 warmup run, 3 timed repetitions averaged.*

---

### Table 1: Hardware-Accelerated Throughput (Vulkan vs. Metal)

| Machine | Model | Backend Configuration | Prompt (`pp512`) | Gen (`tg128`) | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Mac Pro 2013** | 1.5B Q8 | Dual D500 Vulkan (`ngl 99`, `1/1`, `fa 1`) | **392.5 tok/s** | **36.6 tok/s** | 100% VRAM resident |
| **Core Ultra 5** | 1.5B Q8 | Intel Arc Vulkan ANV (`ngl 99`, `fa 1`) | **597.8 tok/s** | **21.2 tok/s** | Mac Pro gen +72% via GDDR5 BW |
| **A18 Pro Laptop** | 1.5B Q8 | Metal (`ngl 99`, `fa 1 \| 0`) | **493.5 tok/s** (535.4) | **31.9 tok/s** (31.1) | Mac Pro leads gen (36.6 vs 31.9) |
| **M4 Max Studio** | 1.5B Q8 | Metal 4 (`ngl 99`, `fa 1 \| 0`) | **3569.7 tok/s** | **164.9 tok/s** | 4.5x Mac Pro gen |
| | | | | | |
| **Mac Pro 2013** | 3B Q4_K_M | Dual D500 Vulkan (`ngl 99`, `1/1`, `fa 1`) | **178.3 tok/s** | **22.1 tok/s** | 100% VRAM resident |
| **Core Ultra 5** | 3B Q4_K_M | Intel Arc Vulkan ANV (`ngl 99`, `fa 1`) | **433.4 tok/s** | **24.1 tok/s** | int_dot Q4 shader |
| **A18 Pro Laptop** | 3B Q4_K_M | Metal (`ngl 99`, `fa 1 \| 0`) | **208.5 tok/s** (228.8) | **26.0 tok/s** (25.5) | 100% Unified RAM |
| **M4 Max Studio** | 3B Q4_K_M | Metal 4 (`ngl 99`, `fa 1`) | **1640.4 tok/s** | **131.9 tok/s** | 100% Unified RAM |
| | | | | | |
| **Mac Pro 2013** | 7B Q4_K_M | Dual D500 Vulkan (`ngl 28`, `1/1`, `fa 1`) | **74.4 tok/s** | **13.0 tok/s** | All 28/28 layers on dual GPUs |
| **Core Ultra 5** | 7B Q4_K_M | Intel Arc Vulkan ANV (`ngl 99`, `fa 1`) | **188.3 tok/s** | **11.7 tok/s** | Mac Pro leads gen (13.0 vs 11.7) |
| **A18 Pro Laptop** | 7B Q4_K_M | Metal (`ngl 99`, `fa 1`) | **96.6 tok/s** | **11.7 tok/s** | Tight fit in 5,726 MB Metal cap |
| **M4 Max Studio** | 7B Q4_K_M | Metal 4 (`ngl 99`, `fa 1`) | **726.4 tok/s** | **70.0 tok/s** | 5.4x faster gen than Mac Pro |
| | | | | | |
| **Mac Pro 2013** | 14B Q4_K_M | Hybrid (`ngl 24`) + 12c Xeon (THP) | **27.6 tok/s** | **6.40 tok/s** | +60% CPU boost via THP |
| **Core Ultra 5** | 14B Q4_K_M | Intel Arc Vulkan ANV (`ngl 99`, `fa 1`) | **95.0 tok/s** | **6.30 tok/s** | Mac Pro hybrid edges gen |
| **A18 Pro Laptop** | 14B Q4_K_M | *OOM / Exceeds 8 GB RAM* | N/A | N/A | Cannot fit 8.37 GiB in 5.33 GiB cap |
| **M4 Max Studio** | 14B Q4_K_M | Metal 4 (`ngl 99`, `fa 1`) | **385.5 tok/s** | **38.6 tok/s** | 100% Unified RAM |
| | | | | | |
| **Mac Pro 2013** | 32B Q4_K_M | 12c Xeon Pure CPU (`-ngl 0 -t 12`, THP) | **9.06 tok/s** | **2.53 tok/s** | Zero PCIe overhead; fits 64 GB RAM |
| **Mac Pro 2013** | 32B Q4_K_M | Hybrid (`-ngl 16`, `1/1`) + Xeon | **3.84 tok/s** | **2.77 tok/s** | +10% gen, throttled prompt |
| **Core Ultra 5** | 32B Q4_K_M | Intel Arc Vulkan ANV (`ngl 99`, `fa 1`) | **41.6 tok/s** | **2.85 tok/s** | Fits in 21.4 GiB Vulkan UMA |
| **A18 Pro Laptop** | 32B Q4_K_M | *OOM / Exceeds 8 GB RAM* | N/A | N/A | Exceeds RAM |
| **M4 Max Studio** | 32B Q4_K_M | Metal 4 (`ngl 99`, `fa 1`) | **165.1 tok/s** | **18.1 tok/s** | Fits 28.08 GiB Metal cap |

---

### Table 2: Normalized Pure CPU Baseline (`-ngl 0`)

| Machine | Model | CPU Thread Config | Prompt (`pp512`) | Gen (`tg128`) |
| :--- | :--- | :--- | :--- | :--- |
| **Mac Pro 2013** | 1.5B Q8 | `-t 8` | **332.8 tok/s** | **27.1 tok/s** |
| **Core Ultra 5** | 1.5B Q8 | `-dev none --no-host 1 -t 8 \| -t 14` | **97.1** (114.8 @ 14T) | **21.3** (21.9 @ 14T) |
| **A18 Pro Laptop** | 1.5B Q8 | `-dev none -t 6 \| -t 2` P-cores | **228.5** (148.0 @ 2T) | **28.6** (34.1 @ 2T) |
| **M4 Max Studio** | 1.5B Q8 | `-dev none -t 8 \| -t 10` P-cores | **843.2** (975.3 @ 10T) | **146.2** (137.1 @ 10T) |
| **Mac Pro 2013** | 7B Q4_K_M | `-t 8` | **59.5 tok/s** | **8.94 tok/s** |
| **Core Ultra 5** | 7B Q4_K_M | `-dev none --no-host 1 -t 8 \| -t 14` | **32.8** (35.8 @ 14T) | **7.61** (8.68 @ 14T) |
| **A18 Pro Laptop** | 7B Q4_K_M | `-dev none -t 6` | **38.3 tok/s** | **9.60 tok/s** |
| **M4 Max Studio** | 7B Q4_K_M | `-dev none -t 8 \| -t 10` | **137.1** (166.3 @ 10T) | **50.07** (54.02 @ 10T) |
| **Mac Pro 2013** | 32B Q4_K_M | `-t 8` | **9.05 tok/s** | **2.08 tok/s** |
| **Core Ultra 5** | 32B Q4_K_M | `-dev none --no-host 1 -t 8 \| -t 14` | **6.94** (7.42 @ 14T) | **1.77** (2.11 @ 14T) |
| **M4 Max Studio** | 32B Q4_K_M | `-dev none -t 8 \| -t 10` | **27.7** (35.4 @ 10T) | **11.80** (12.98 @ 10T) |

---

### Table 3: Multimodal Vision (Moondream2 F16)

| Machine | High-Res UI (2939×2499) Encode / Total | Photo (640×427) Encode / Total |
| :--- | :--- | :--- |
| **Mac Pro 2013** | **1,749 ms** / **7.8 s** | **1,753 ms** / **8.2 s** |
| **Core Ultra 5** | **1,607 ms** / **10.36 s** | **1,628 ms** / **11.30 s** |
| **A18 Pro Laptop** | **659 ms** / **4.27 s** | **650 ms** / **6.90 s** |
| **M4 Max Studio** | **100 ms** / **0.97 s** | **99 ms** / **1.27 s** |

---

### Table 4: Power & Energy Efficiency

| Machine | Measured Idle Draw | Power Envelope | 7B (`tg128`) | 1K-Token Runtime | Efficiency Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Mac Pro 2013** | **120 W** *(wall meter)* | 120 W idle floor + 130 W Xeon / Dual D500 load | **13.0 tok/s** | **76.9 s** | `<= 0.108 tok/s/W` at 120 W floor (`2.88 kWh/day` 24/7) |
| **Core Ultra 5** | Low laptop idle | **28 W** sustained `intel-rapl:0` PL1 ceiling | **11.7 tok/s** | **85.5 s** | `~0.42 tok/s/W` (~4x+ higher perf/Watt) |
| **A18 Pro Laptop** | **3.4 W** *(`ioreg` 3.38–3.43 W)* | **<= 20 W** USB-C adapter cap | **11.7 tok/s** | **85.5 s** | 35x lower idle; `>= 0.59 tok/s/W` on 7B |
| **M4 Max Studio** | Desktop Apple Silicon | High-speed unified SoC | **70.0 tok/s** | **14.3 s** | Finishes 7B tasks **5.4x faster** than Mac Pro |

> **Operational Tip:** With `performance` governor and DPM `high` active, the 2013 Mac Pro idles near ~120 W (`2.88 kWh/day` if left running 24/7). Use Wake-on-LAN or a smart plug for on-demand workdays rather than continuous 24/7 idling. Live RAPL + Apple SMC power monitoring is built directly into `sudo trash-top`.
