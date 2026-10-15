# Strata seat

Strata (`https://github.com/Niko1221/Strata`) is a local inference server with an Anthropic-compatible
endpoint. The `strata` seat runs Claude Code against it as a co-programmer.

**Strata is standalone.** It shares nothing with the `lmstudio` seat: no `lmstudio_shim.py`, no `lms`,
no LM Studio context/GPU settings, and no `lmstudio_*` config keys. Configure it only from Strata's
own docs and its install.

## The configuration lives in the Strata install

Conspirator stores only where Strata is installed (`strata_home`). Every run reads the rest from the
install, so a reinstall, retune or model switch is picked up automatically:

```text
strata_home\strata_agent.py   launcher used in place of `claude`
  -> strata-up.ps1            $StartScript = the model's run-*.bat, $Port
  -> run-<model>.bat          --config strata-<model>.json
  -> strata-<model>.json      engine args, model_name, port, reasoning/recovery options
  -> GET /health              what is actually loaded
```

Always check the live configuration before relying on any value:

```text
python <skill-dir>/scripts/pairctl.py strata          # human-readable
python <skill-dir>/scripts/pairctl.py strata --json   # everything, including engine args
```

It exits 1 and prints `PROBLEM` lines when a file is missing or the server runs a different model
than the installed config. `pair`, `dispatch`, `swarm` and `swarm --review` run the same check and
refuse a `strata` seat while a problem exists. `doctor --implementer strata` includes it.

## Dispatch shape

```text
python <strata_home>\strata_agent.py -p <compact prompt> --output-format json
       --permission-mode acceptEdits --allowedTools Bash,Read,Edit,Write,Glob,Grep --add-dir <main>/.git
```

cwd = the brief's worktree. `strata_agent.py` starts Strata if needed, waits until it is loaded and
warm, holds the display awake (Modern Standby on the ROG Flow Z13 cuts Strata to a third of its
speed), and sets `ANTHROPIC_BASE_URL`, the auth token, the model aliases and `API_TIMEOUT_MS`. The
seat passes no `--model`: the model is whatever the install is set up for. The review variant is
read-only (`Read,Glob,Grep` and `git diff/log/show`).

## Config keys

```text
implementer=strata          (or --implementer strata; not in the default auto priority)
strata_home=C:\DEV\GIT\Strata
strata_command=claude       the CLI strata_agent.py wraps; must be on PATH
strata_extra_args=[]
```

## Installed configuration on this PC (snapshot 2026-10-15)

`pairctl strata` is the authority; this is a record of what it reported when the seat was added.

- Machine: ASUS ROG Flow Z13 GZ302EA, Ryzen AI Max+ 395, Radeon 8060S (gfx1151), 124 GB, Windows 11.
- Strata repo `C:\DEV\GIT\Strata` (engine 0.1.44.1); models under `C:\DEV\IDE\Strata`.
- Only model installed: **Qwen3.8 Flash Next Unsloth UD-IQ4_XS** (`model_name`
  `qwen3.8-flash-next-unsloth-ud-iq4_xs`), chosen over Original IQ3_S, Coder IQ1_M and Swift 1.5 IQ3_S
  in a five-task coding benchmark with hidden acceptance tests (all correct, fastest overall).
- Launcher `run-unsloth-ud-iq4_xs.bat` -> `strata-unsloth-ud-iq4_xs.json`, port 8080.
- Engine: HIP backend, `--max-context 131072`, `--kv int8`, `--kv-resident 32768`, `--expert-cache 17195`
  (all 24,576 expert slots on the GPU), `--resident-budget-gib 55`, `--prefill 16384`,
  `--no-prefill-borrow`, `--vram-reserve-mib 4096`, `--spec 4 --spec-min-p 0.5` with the MTP draft head,
  `--lookup-chain 3`, conversation cache 4096 MiB / 3 slots / 4096 min tokens.
- Server options: `fit_max_tokens`, `tool_call_recovery`, `reasoning_close_retry`,
  `reasoning_loop_recovery: stop`, `reasoning_effort: medium`.
- Throughput: about 40 tok/s decode and 600 tok/s prompt with the display awake. Load is ~5 minutes.
- Stop the server with `POST /unload` (Content-Type: application/json). Native-pack models (not
  installed now) need `--resident-experts` and `--expert-cache 20000` on this PC or the engine exits at start.
