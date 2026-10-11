# Troubleshooting

Start with [diagnostics](getting-started.md). Logs live in `workspace/cache/checks/` or `workspace/cache/`; sanitize excerpts before reporting. Missing tools, skips and pending reviews are incomplete verification.

| Symptom | Action |
|---|---|
| Missing/unsupported toolkit marker | Use a complete checkout or `--toolkit-root`/`EDITING_PACK_ROOT`, not an unrelated parent. |
| Missing config or unknown field | Fix the named UTF-8 JSON and compare with `config/toolkit.example.json`; explicit bad paths do not fall back. |
| Overlapping workspace | Use a dedicated sibling/external folder; inspect resolved links/junctions. |
| Output outside workspace | Make CLI/environment/config agree and keep output inside it; config-relative paths resolve beside config. |
| FFmpeg/FFprobe missing | Configure executable files or PATH. Doctor exit 0 means a report exists; inspect availability fields. |
| jsonschema import error | Install the core lock into the selected isolated interpreter. |
| Argument errors with spaces | Quote whole paths; common options go before a subcommand. |
| HyperFrames/resource mismatch | Reinstall pinned external packages with scripts disabled; configure exact CLI/assets and intact Inter license. No npx fallback. |
| Browser/render failure | Configure a working Chrome Headless Shell and inspect render logs. The tested Edge executable failed HyperFrames Windows version preflight; see installation. Lint success is not render success. |
| Preview port occupied | Identify/close its owning session if appropriate. Never kill another task's server. |
| WhisperX unavailable | Use compatible optional setup or evidenced aligned words; never relabel raw ASR. |
| MCP wrapper import fails | Use pinned v1 environment; MCP v2 differs. Tested dependencies emit a Pydantic forward-reference warning but tool discovery passes; native execution remains unverified. |
| Mailbox expired/missing | Configure both Python/native process, start an authorized bounded Lua session and verify identity. Never replay into another project. |
| FCPXML blocked | Supply matching installed DTD and xmllint; do not remove validation or infer import proof. |
| Authority/treatment rejected | Correct missing/stale real evidence, rehash current bytes and obtain real review. Do not edit pass flags. |
| Captions drift after edits | Regenerate from approved timeline map/retimed words; do not invent a second clock. |
| Quality ready false | Resolve failing/pending items, required regression/waiver and exact-artifact review. Automated pass alone is insufficient. |
| Hosted cost/terms refusal | Check current account prices/terms and explicitly approve paid execution. Planning is default. |

## CLI help

From the toolkit root using the core interpreter:

```powershell
$ToolkitPython = '../editing-pack-env/Scripts/python.exe'
& $ToolkitPython -B 'Editing_OS/Tools/editing-workbench/workbench.py' --help
& $ToolkitPython -B 'Editing_OS/Video Editing/Engines/Orchestration_adapter/adapter.py' --help
& $ToolkitPython -B 'Editing_OS/Video Editing/Engines/Captions_engine/engine.py' --help
& $ToolkitPython -B 'Editing_OS/Video Editing/Engines/Graphics_engine/compose.py' --help
& $ToolkitPython -B 'Editing_OS/Video Editing/Engines/Quality_engine/qa.py' --help
```

A [public bug report](../.github/ISSUE_TEMPLATE/bug_report.md) needs revision, platform/Python, tool versions, expected/actual results and a synthetic reproduction. Security/private data uses [SECURITY](../SECURITY.md).
