# Windows desktop app

HENTAI Studio's Windows client is a native .NET 8 Windows Forms application. Project lists, job history, dialogs, console output, file downloads, and scratch-model chat use Windows controls. The metric chart is drawn with GDI+. The app does not embed WebView2, Chromium, HTML, or JavaScript, and does not require the WebView2 Runtime.

The desktop client talks to Studio's JSON API. A backend can run on the same computer, in WSL, or on AWS through an SSH tunnel. Paths, commands, checkpoints, and training processes belong to the backend machine. HENTAI Studio does not require the HENTAI diffusion-model repository.

## Build and install

Requires the .NET 8 Desktop Runtime to run, or the .NET 8+ SDK to build:

```powershell
./windows/HENTAIStudio/build.ps1
```

The resulting executable is `dist/HENTAIStudio/HENTAI Studio.exe`. Publishing produces a framework-dependent single-file application. Copy only this executable when updating the desktop client; old browser-related build artifacts are unnecessary.

`build.ps1 -Install -Python C:\path\to\python.exe` installs the application, creates a private Python backend environment, and creates Desktop and Start menu shortcuts. Installation preserves application and workspace directories. Python is needed on the machine running a backend; connecting to an existing backend needs only the Windows client and .NET Desktop Runtime.

## Connect and use multiple windows

Studio opens a native port picker. Enter a local backend port or a forwarded SSH port. Connecting starts no backend unless you check **Start a local Studio backend if none is running**.

```powershell
& '.\HENTAI Studio.exe' --pick-port 8786
& '.\HENTAI Studio.exe' --connect http://127.0.0.1:8786/
```

Use **New window…** or **Ctrl+N** for another independent connection. The title shows the port and the backend's Local/Cloud flag. **Refresh** or **F5** retries a failed connection. The client accepts HTTP loopback origins; use SSH forwarding for remote machines rather than exposing the backend publicly.

Windows snap and ordinary resizing work down to a 440-pixel window width. Projects and job history move above the details at narrow widths. Job history uses native table rows with resizable columns, horizontal scrolling, and full-name tooltips. Long names cannot wrap into the next row. Font scaling follows Windows DPI settings.

The scratch LLM editor configures local architecture, tokenizer, dataset, and training options. The native chat tester explicitly loads saved weights on the backend, supports CPU or CUDA, and keeps conversations separate by project. No remote inference provider is involved.

Closing a window cancels that window's pending API requests. It does not send a stop command to trainers or shut down a backend. Use **Stop job** explicitly to stop training.

## Local backend configuration

The **Hardware** tab reads live CPU, RAM, and GPU telemetry from the selected backend, including NVIDIA, AMD, and Intel adapters. It requires Studio backend 0.8 or newer. See [Hardware monitoring](HARDWARE.md) for sensor availability and remote server updates. Missing hardware readings do not disable job controls.

Optional environment overrides: `STUDIO_EXECUTABLE` (backend executable), `STUDIO_WORKSPACE` (workspace directory), and `STUDIO_URL` (default loopback URL/port). When local startup is explicitly selected, the app looks for `backend/Scripts/hentai-studio.exe` beside itself, then uses PATH. Backend logs go to `<workspace>/logs/server.log`.

The browser dashboard remains available separately from the backend for browser users. The Windows app does not load it.
