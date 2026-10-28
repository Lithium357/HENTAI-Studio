# Windows desktop app

Requires .NET 8 Desktop Runtime and Microsoft WebView2 Runtime. Build with:

```powershell
dotnet build windows/HENTAIStudio/HENTAIStudio.csproj --configuration Release
```

The shell uses the same default workspace as the CLI, verifies `/api/health` identifies Studio, reports occupied ports, and writes backend logs to `<workspace>/logs/server.log`. It can reconnect to an existing backend or start one without keeping a console window open.

`windows/HENTAIStudio/build.ps1` publishes the shell only. `build.ps1 -Install -Python C:\path\to\python.exe` explicitly installs the shell, creates its own backend environment and installs Studio into it. Installation copies files without recursively deleting existing application/workspace directories.

Optional overrides: `STUDIO_EXECUTABLE` (backend executable), `STUDIO_WORKSPACE` (workspace directory), `STUDIO_URL` (HTTP loopback URL/port). Without an override the shell first looks for an installed `backend/Scripts/hentai-studio.exe` beside it, then uses PATH. For an existing Python installation, set `STUDIO_EXECUTABLE` to that environment's full `hentai-studio.exe` path.

