# AUTONOMOUS_TROUBLESHOOTING — 親ラボでの障害検出と復旧

以下の監視・再起動・基準ステート復元は[研究環境](README.md)の自動化手順です。`ps2lab` と実験用ステートは同梱していません。公開 GUI が同じ処理を行ったり、利用者のセーブを自動復元したりするわけではありません。

## 1. The loop

```
        ┌──────────────┐
        │  observe     │  health(), tool results, logs, screenshots
        └──────┬───────┘
               ▼
        ┌──────────────┐
        │  classify    │  ps2lab.recovery.classify() → failure class
        └──────┬───────┘
               ▼
        ┌──────────────┐   new evidence?
        │  research    │───────────────┐
        └──────┬───────┘               │
               ▼                       ▼
        ┌──────────────┐        ┌──────────────┐
        │  hypothesise │        │ web_search / │
        │  (≤3 causes) │        │ web_fetch    │
        └──────┬───────┘        └──────────────┘
               ▼
        ┌──────────────┐
        │  repair      │  config patch / restart / reconnect / code patch
        └──────┬───────┘
               ▼
        ┌──────────────┐
        │  verify      │  replay the failing step + regression checks
        └──────┬───────┘
               ▼
        ┌──────────────┐
        │  record      │  reports/troubleshooting_history.json + KB entry
        └──────────────┘
```

## 2. Failure classes and automatic actions

| Class | Detection | Automatic action |
|---|---|---|
| `process_missing` | `psutil` scan | launch the configured ISO and wait for ports |
| `gdb_port_closed` | TCP probe on 10501/10502 | terminate + relaunch (GDB listeners are re-created) |
| `mcp_disconnected` | `status` shows `connected:false` | `connect` with `auto_resume`, then resume |
| `pine_unreachable` | PINE version request | restart emulator, re-open PINE |
| `not_responding` | `SendMessageTimeoutW` on the render window | restart emulator |
| `low_disk` | `psutil.disk_usage` < 5 GB | abort mutating experiments, report |
| `black_screen` | pixel statistics | resume, wait for content, retry capture |
| `unknown` | fallback | bounded retry, then isolate the phase |

Retry budget: 3 attempts per step, exponential sleep (2 s, 4 s, 8 s), then the
supervisor escalates to a restart; the E2E harness isolates the phase so later
phases still produce evidence.

## 3. Concrete repairs performed autonomously in this build

These were not scripted in advance — each came from an observed failure:

1. **Git over HTTPS failed** → diagnosed restricted-token/schannel →
   switched the TLS backend to OpenSSL (KB-01).
2. **PowerShell downloads failed** → same root cause → moved downloads to
   Python/OpenSSL with resumable range requests (KB-02).
3. **No GDB in stock PCSX2** → proved by binary string scan → located the
   maintainer's fork, verified its SHA-256, swapped the runtime (KB-03).
4. **qPcsx2 argument parsing broken** → isolated with sentinel probes →
   added Capstone disassembly, GDB `Z1`/`Z2` fallbacks, keyboard input (KB-04).
5. **Register reads zeroed after connect** → added a resume/pause flush and
   retries until `sp` is in RAM (KB-08).
6. **EE listener dying between phases** → found that a diagnostic probe evicted
   the single MCP client → probe only when disconnected, restart on dead
   listener (KB-09).
7. **PINE protocol mismatch** → discovered TCP transport + length-prefixed
   framing → rewrote the client; verified byte-for-byte against GDB (KB-10).
8. **Ghidra rejected `r5900:LE:32:default`** → extension modules were not
   registered in headless mode → compiled `r5900.slaspec` with `support/sleigh`,
   installed the language files into the MIPS module, verified import (KB-18).
9. **Ghidra download stalled** → resumable downloader with SHA-256 gate (KB-16).

## 4. Guardrails (why this stays safe)

* Destructive experiments are limited to: the ISO working copy, savestate slots
  (`0…9`), scratch RAM (`0x01FF0000`), and `PCSX2.ini` (backed up first).
* Every mutation has a paired restore and a verification read.
* No security feature is disabled, no kernel driver installed, no credentials
  written anywhere.
* Ports stay on localhost; PINE/GDB are single-client, so the lab serialises
  access instead of racing.
* Stop conditions (`BLOCKERS.md`) are honoured: when a requirement needs user
  data, administrator rights, or an unsupported feature, the lab stops and
  documents instead of hacking around it.

## 5. Recording

* `logs/supervisor.jsonl` — every health decision and repair, append-only.
* `reports/troubleshooting_history.json` — structured history for the model.
* `TROUBLESHOOTING_KB.md` — human-readable, deduplicated knowledge.
* `reports/e2e_results.json` — per-step PASS/FAIL plus supervisor history per run.

Before investigating a new symptom, the lab reads the KB; if the symptom matches
but the local evidence differs (different version, different port state), the
entry is treated as a *hypothesis*, not a fix.
