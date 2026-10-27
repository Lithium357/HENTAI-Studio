# Command line

```text
hentai-studio serve [--workspace PATH] [--host 127.0.0.1] [--port 7860] [--log-file PATH]
```

The workspace defaults to `~/.hentai-studio` and is created if absent. Explicit `~` paths are expanded. Studio starts empty, with no project or training configuration required. Use the dashboard or typed API to register projects.

The log-file option appends server/error/access logs to a durable UTF-8 file. Without it, Uvicorn logs normally to the console. The Windows shell supplies this option so backend logging survives closing the shell.

Only one dashboard process may serve a workspace. Closing the server leaves job supervisors running. Reopening the same workspace reconnects to them. The default host is loopback; Host validation also permits a concrete host explicitly passed at startup. Studio has no account/authentication system.

The old dashboard/studio modes and `llm-*` commands are removed. No ML package extra exists. Run each trainer through that project's own environment and register its real argument arrays. See MIGRATION.md for recovering the historical bundled tools.
