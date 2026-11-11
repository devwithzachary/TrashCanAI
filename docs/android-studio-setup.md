# Android Studio & JetBrains IDE Integration

Because [`scripts/serve.sh`](../scripts/serve.sh) exposes an OpenAI-compatible REST API (`http://<MAC_PRO_IP>:8080/v1`) via `llama-server --models-preset`, you can wire Android Studio directly to your 2013 Mac Pro over LAN.

---

## Option A: Native Remote OpenAI Provider (Android Studio)

1. Open **Settings** -> **Tools** -> **AI** -> **Models** (or **Model Providers** depending on Android Studio version).
2. Add a custom **OpenAI-compatible Remote Provider**:
   * **Name**: `TrashCan AI (Mac Pro)`
   * **Base URL**: `http://<MAC_PRO_IP>:8080/v1`
   * **API Key**: `not-needed` *(any non-empty placeholder string)*
   * **Model IDs**:
     * `trash-code` (Qwen 2.5 Coder 7B — Dual D500, default daily coder)
     * `trash-fast` (Qwen 2.5 Coder 1.5B — rapid autocomplete)
     * `trash-deep` (Qwen 2.5 Coder 14B — hybrid deep debugging)
     * `trash-heavy` (Qwen 2.5 Coder 32B — 64 GB ECC architectural tasks)
     * `trash-social` (Qwen 2.5 3B — text/grammar cleanup)

---

## Option B: Right-Click External Tools via `trash-ai`

Wiring JetBrains **External Tools** to [`scripts/trash-ai`](../scripts/trash-ai) gives one-click streaming output right inside Android Studio's Run tool window and automatically selects the optimal model preset per action.

1. On your workstation, symlink `scripts/trash-ai`:
   ```bash
   mkdir -p ~/.local/bin
   ln -sf /path/to/trashAI/scripts/trash-ai ~/.local/bin/trash-ai
   ```
   *(Set `export TRASH_AI_HOST=<MAC_PRO_IP>` in your shell profile, or pass `--host <MAC_PRO_IP>` in each tool's Arguments.)*

2. In Android Studio: **Settings** -> **Tools** -> **External Tools** -> **`+`**, and create tools with:
   * **Working directory**: `$ProjectFileDir$`

| Tool Name | Program | Arguments |
| :--- | :--- | :--- |
| **Ask Prompt (7B Dual-GPU)** | `trash-ai` | `--host <MAC_PRO_IP> code -f "$FilePath$" --lines $SelectionStartLine$-$SelectionEndLine$ "$Prompt$"` |
| **Review & Improve Code (7B)** | `trash-ai` | `--host <MAC_PRO_IP> code -f "$FilePath$" --lines $SelectionStartLine$-$SelectionEndLine$ "Review for bugs, edge cases, and cleaner Kotlin/Linux patterns"` |
| **Deep Refactor (14B Hybrid)** | `trash-ai` | `--host <MAC_PRO_IP> code --deep -f "$FilePath$" --lines $SelectionStartLine$-$SelectionEndLine$ "Refactor carefully and explain key improvements"` |
| **Architecture / Hard Bug (32B RAM)** | `trash-ai` | `--host <MAC_PRO_IP> code --heavy -f "$FilePath$" "$Prompt$"` |
| **Proofread Selection (3B)** | `trash-ai` | `--host <MAC_PRO_IP> spellcheck -s "$SelectedText$"` |

Highlight lines in any Kotlin/Java/XML/Bash file -> Right-click -> **External Tools** -> **Review & Improve Code** while watching `sudo trash-top` over SSH.

