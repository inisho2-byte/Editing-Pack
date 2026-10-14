# Configuration and external workspaces

The root `toolkit.json` identifies this toolkit. The shared runtime discovers it from its own module location, not from a household repository or home directory. An explicit `--toolkit-root` or `EDITING_PACK_ROOT` overrides discovery.

Configuration comes from `--config` / `EDITING_PACK_CONFIG`, otherwise the ignored `config/toolkit.local.json`. The example config is never automatically loaded. An explicitly named missing config or tool fails with an actionable error instead of silently changing tools.

Workspace precedence is `--workspace`, `EDITING_PACK_WORKSPACE`, then config `workspace_root`. Tool precedence is an explicit API path, `EDITING_PACK_<TOOL_NAME>`, config `tools`, then PATH for ffmpeg/ffprobe/node only. File assets and browsers require explicit paths. CLI/environment relative paths resolve from the working directory; config-relative paths resolve beside the config file. `external_tools_root` is descriptive and does not trigger discovery or installs.

The toolkit and workspace cannot contain one another, including resolved links/junctions. CLI job outputs must stay inside the selected workspace. Library calls also reject output inside the toolkit and enforce the workspace when configured. Choose a dedicated folder, not your home, drive or operating-system root.

Suggested workspace layout:

```text
jobs/<job>/brief/
jobs/<job>/inputs/
jobs/<job>/contracts/
jobs/<job>/work/
jobs/<job>/evidence/
jobs/<job>/exports/
cache/
dependencies/model-cache/
```

Common runtime options must appear before a subcommand where one exists. For example:

```powershell
$ToolkitPython = '../editing-pack-env/Scripts/python.exe'
& $ToolkitPython -B 'Editing_OS/Tools/editing-workbench/workbench.py' --config config/toolkit.local.json doctor --out ../editing-workspace/evidence/doctor.json
& $ToolkitPython -B 'Editing_OS/Tools/editing-workbench/hyperframes_launcher.py' --config config/toolkit.local.json --list
```

The doctor is diagnostic only. The launcher retains its graphical library and CLI modes; preview servers are foreground children owned by that launcher. Closing it or interrupting a CLI preview stops its owned process tree. It refuses an occupied port 3100. It does not reuse or stop another task's server, install HyperFrames, or register a sign-in task. Logs and process ownership records stay in workspace/cache. A bounded live preview check confirmed HTTP readiness and shutdown on the tested Windows setup; full UI editing/render verification remains pending.

Config files contain paths and environment variable references, never credentials or human approval. Synthetic context examples are fixtures, not approvals. Every real job hashes the current five governing documents and collects its own alignment, EDL, treatment, encoded QA and exact-artifact human review evidence.

## New optional resource fields

`tools.three_module` and `tools.puppeteer_entry` are explicit file paths for the
native 3D browser profile. Existing configurations remain valid without these
fields; enabling that profile requires them plus Node, browser, GSAP and Inter.
The runtime derives matching Three core/addons from the exact installed package.
Pillow is an optional Python profile, not a JSON tool path. Configuration never
installs packages or supplies human authority. See [installation](installation.md).
