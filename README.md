# AgentChattr Control Panel (ACP)

A Windows-friendly GUI (PyQt6 + QFluentWidgets) that installs, configures, and runs **agentchattr** with **Codex CLI** and **Gemini CLI**.

## What this app manages

- **Setup**: Clone/update `bcurts/agentchattr`, create `.venv`, install Codex CLI and Gemini CLI (via npm)
- **Workspaces**: Define workspace folders where Codex/Gemini run; set the active workspace
- **Config**: Write `config.toml`, apply workspace to agents, set server host/port
- **LAN & Security**: Set LAN IP, patch `app.py` for LAN Origin, start server with `--allow-network`
- **Run**: Start/stop the agentchattr server, open chat in browser, launch Codex/Gemini wrappers in console windows
- **Logs**: Stream output from git, pip, npm, and server

## Requirements

- **Python 3.11+**
- Windows 10/11 recommended
- **Git** (for cloning/updating agentchattr)
- **Node.js + npm** (only if you want ACP to install Codex/Gemini CLIs for you)

## Install & run

**Option A — use the batch script (recommended):**

```bat
run_acp.bat
```

This creates a venv if needed, installs dependencies, and launches ACP.

**Option B — manual steps:**

```bat
cd /d <this-folder>
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
pip install -e .
python -m acp
```

## Usage

The UI is ordered by workflow. Follow the tabs left to right for a first-time setup.

### 1. Setup

1. Enter the path where agentchattr should live (existing folder or empty folder to clone into), or click **Browse**.
2. **Clone** — clones `bcurts/agentchattr` into the selected folder (folder must be empty).
3. **Pull** — updates an existing clone with `git pull --ff-only`.
4. **Create/Repair** — creates `agentchattr/.venv` and installs `requirements.txt`.
5. **Install Codex CLI** / **Install Gemini CLI** — optional; installs the CLIs globally via npm.
6. Click **Refresh** to update status. Green ticks (✓) show what’s already done.

### 2. Workspaces

Workspaces are folders where Codex and Gemini run (e.g. your project directory).

1. Enter a **Name** and **Folder path**, or use **Browse**.
2. Use **Create folder** if the path doesn’t exist.
3. Click **Add** to add the workspace.
4. Select a workspace in the list and click **Set active**.
5. The active workspace is used when you apply config in the Config tab.

### 3. Config

1. Set **server.host** (e.g. `127.0.0.1` or your LAN IP) and **server.port**.
2. **Apply** — writes the active workspace into `config.toml` so Codex/Gemini run in that folder.
3. **Write** — creates a clean default `config.toml`.
4. **Save** — saves host/port and MCP ports to `config.toml`.

### 4. LAN & Security (optional)

For using the chat UI from another device on your LAN:

1. Select your LAN IP from the dropdown or type it in.
2. Click **Apply** to set the host.
3. Click **Patch** to patch `app.py` so it accepts requests from your LAN IP.
4. In Config, save the host. When you start the server, it will use `--allow-network` if the host is not localhost.

### 5. Run

1. **Start** — starts the agentchattr server.
2. **Open** — opens the chat UI in your browser.
3. **Start Codex** / **Start Gemini** — opens a console window running the wrapper for that agent.
4. **Stop** — stops the server. **Stop wrappers** kills Codex/Gemini wrapper processes.

### 6. Logs

Shows output from Setup actions (git, pip, npm) and from the server when started from ACP. ANSI colors are supported.

---

**Workflow summary:** Setup → Workspaces → Config → (optional) LAN → Run

## Notes on QFluentWidgets

QFluentWidgets uses the import name `qfluentwidgets`. **Do not install multiple variants at once** (PyQt-Fluent-Widgets / PyQt6-Fluent-Widgets / PySide6-Fluent-Widgets), because they share that module name.

This project uses **PyQt6-Fluent-Widgets**.

## Licensing

`PyQt6-Fluent-Widgets` is **GPLv3**. If you distribute ACP, you must comply with GPLv3. For private/internal use this is usually fine; do not ship closed-source without checking.

## Packaging

```bat
.venv\Scripts\pip install pyinstaller
.venv\Scripts\pyinstaller --noconfirm --onefile --name AgentChattrControlPanel -m acp
```

Use `--windowed` to hide the console.

## Why pip prints `Obtaining file:///...`

ACP uses `pip install -e .` (editable install) so the `src/` layout imports work without copying files.
