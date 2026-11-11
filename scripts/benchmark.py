#!/usr/bin/env python3
"""
TrashCanAI Benchmark Runner
Measures prompt processing (prefill) and token generation speed across models
using llama-bench or llama-cli with standardized real-world prompts.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_PROMPTS = {
    "grammar_spellcheck": (
        "Correct all grammar and spelling mistakes in the following text, and output only the polished version:\n\n"
        "Their are many reason why local AI is better then cloud ai. First, privacy is much more higher because you're "
        "data never leaves you're local harddrive. Second, their is no subcription fees after you buyed the hardware."
    ),
    "hashtags_social": (
        "Generate 8 punchy, highly relevant hashtags and a 2-sentence engaging social media post caption "
        "about reviving a 2013 Apple Mac Pro into an offline local AI coding and writing workstation."
    ),
    "coding_android": (
        "Write a concise Kotlin Jetpack Compose function named `TrashCanDashboard` that displays CPU temperature, "
        "dual GPU VRAM usage bars, and current tokens-per-second generation rate using Material 3 Card components."
    ),
    "coding_linux": (
        "Write a robust bash script that monitors GPU temperature and memory usage on AMD Tahiti FirePro D500 GPUs "
        "via sysfs (/sys/class/drm) and logs any throttling events to a timestamped file."
    ),
}


def run_llama_bench(llama_bench_bin, model_path, ngl=99, split_mode="layer", tensor_split="1/1", threads=12):
    """Run llama-bench in JSON output mode."""
    cmd = [
        str(llama_bench_bin),
        "-m", str(model_path),
        "-n", "128",
        "-p", "512",
        "-ngl", str(ngl),
        "-sm", split_mode,
        "-ts", tensor_split,
        "-t", str(threads),
        "-fa", "1",
        "-o", "json",
    ]
    print(f"[*] Running: {' '.join(cmd)}")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(res.stdout)
    except Exception as exc:
        print(f"[-] llama-bench failed: {exc}")
        return None


def run_task_prompt(llama_cli_bin, model_path, task_name, prompt_text, ngl=99, split_mode="layer", tensor_split="1,1", threads=12):
    """Run a task prompt through llama-cli and print timing statistics."""
    cmd = [
        str(llama_cli_bin),
        "-m", str(model_path),
        "-p", prompt_text,
        "-n", "256",
        "-ngl", str(ngl),
        "-sm", split_mode,
        "-ts", tensor_split,
        "-t", str(threads),
        "--temp", "0.2",
    ]
    print(f"\n[*] Running Task: {task_name}")
    start = time.perf_counter()
    res = subprocess.run(cmd, capture_output=True, text=True)
    duration = time.perf_counter() - start

    print(f"--- Output for {task_name} ---")
    print(res.stdout.strip())
    print("-------------------------------")
    print(f"Completed in {duration:.2f}s")
    return {
        "task": task_name,
        "duration_sec": duration,
        "raw_stdout": res.stdout,
        "raw_stderr": res.stderr,
    }


def main():
    parser = argparse.ArgumentParser(description="TrashCanAI Benchmark Harness")
    parser.add_argument("--bin-dir", default=str(Path.home() / "llama.cpp/build/bin"), help="Path to llama.cpp binaries")
    parser.add_argument("--model", required=True, help="Path to GGUF model")
    parser.add_argument("--ngl", type=int, default=99, help="Number of GPU layers to offload")
    parser.add_argument("--split-mode", default="layer", choices=["layer", "row", "none"])
    parser.add_argument("--tensor-split", default="1/1", help="VRAM ratio split for dual GPUs (use slash in llama-bench)")
    parser.add_argument("--threads", type=int, default=12, help="CPU threads to use")
    parser.add_argument("--tasks", action="store_true", help="Run practical task prompts")
    parser.add_argument("--bench", action="store_true", help="Run synthetic llama-bench test")

    args = parser.parse_args()
    bin_dir = Path(args.bin_dir)
    llama_bench = bin_dir / "llama-bench"
    llama_cli = bin_dir / "llama-cli"

    if args.bench:
        if not llama_bench.exists():
            print(f"[-] {llama_bench} not found. Build llama.cpp first.")
            sys.exit(1)
        data = run_llama_bench(llama_bench, args.model, args.ngl, args.split_mode, args.tensor_split, args.threads)
        if data:
            print(json.dumps(data, indent=2))

    if args.tasks:
        if not llama_cli.exists():
            print(f"[-] {llama_cli} not found. Build llama.cpp first.")
            sys.exit(1)
        cli_split = args.tensor_split.replace("/", ",")
        for task_name, prompt in DEFAULT_PROMPTS.items():
            run_task_prompt(llama_cli, args.model, task_name, prompt, args.ngl, args.split_mode, cli_split, args.threads)


if __name__ == "__main__":
    main()
