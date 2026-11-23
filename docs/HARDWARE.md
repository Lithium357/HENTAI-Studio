# Hardware monitoring

Open **Hardware** in the native Windows app. The browser dashboard has a **Live backend hardware** disclosure above the workspace. Both read `GET /api/hardware` from Studio 0.8 or newer.

Readings come from the **backend host**, across all workloads. An AWS connection reports the AWS machine, not the desktop GPU. Historical trainer metrics remain in Overview and are labelled as recorded values in the native app. They are not substituted for live measurements.

The monitor reports CPU usage, host RAM, and one row per GPU, with its identity, vendor, utilization, dedicated memory, shared memory when available, temperature, power, and provider. Missing sensor values are `null` in the API and **—** in the interface. Idle utilization is **0%**. Memory values use MiB (1024 × 1024 bytes).

| GPU / backend | Provider | Readings |
| --- | --- | --- |
| NVIDIA, Windows or Linux (including AWS) | `nvidia-smi` from the installed driver | Utilization, dedicated memory, temperature, power, device identity |
| AMD, Windows | DXGI adapter identities + Windows WDDM GPU performance counters | Busiest-engine utilization, dedicated/shared memory, name and capacity |
| Intel, Windows | Same vendor-neutral Windows counters; optional XPU-SMI 2.x | Utilization, dedicated/shared memory; additional sensors through XPU-SMI when supported |
| AMD, Linux | DRM sysfs + hwmon | Utilization, VRAM, temperature and power where the driver exposes them |
| Intel, Linux | XPU-SMI 2.x; DRM/sysfs fallback | XPU-SMI provides utilization, memory and sensors; sysfs fallback exposes only available driver files |

Windows GPU counters require a working WDDM driver. Adapter identity and memory capacity come from DXGI, rather than the old WMI `AdapterRAM` field, which cannot represent modern VRAM capacities reliably. Process-engine utilization is grouped by adapter LUID and physical engine; the monitor reports the busiest engine rather than adding unrelated engines into a percentage above 100. Unsupported Windows temperature/power sensors remain unavailable. The legacy AMD-only Rust probe is not required or executed.

Intel XPU-SMI 2.x is optional and must be installed on the backend machine if needed. Older versions that do not support the queried CSV fields fall back to OS counters and report a provider issue. No tool or GPU driver is installed automatically. NVIDIA SMI uses the installed driver tool, with fallback discovery for older Windows installations and WSL's `/usr/lib/wsl/lib/nvidia-smi`.

WSL and containers can expose fewer readings than the physical host. AMD/Intel GPUs may not appear as Linux DRM cards under WSL. For local Windows GPU readings, run the backend on Windows; for cloud readings, run it on the GPU instance. Missing passthrough, unsupported sensors, and provider failures are reported in `issues`.

One background sampler serves every window connected to a backend. Collection starts on the first hardware request, samples roughly every three seconds plus collection time, and bounds external helper execution with timeouts. Requests return the cached snapshot immediately, including while a driver is slow. `sampled_at`, `age_seconds`, `collecting`, and `stale` distinguish initialization, current measurements, and old data. Samples older than 15 seconds are marked stale. Monitoring never loads model weights, changes driver settings, or signals training processes.

## Updating an existing backend

Updating only the desktop executable does not add the endpoint to a remote server. Install Studio 0.8 on each backend using that backend's environment, then restart **only its Studio API server**, preserving its workspace and independent training supervisors:

```sh
python -m pip install --upgrade git+https://github.com/Lithium357/HENTAI-Studio.git
```

Keep the existing server command, port, workspace, and `--location` flag. The Hardware panel reports an unavailable endpoint when connected to an older server; other controls continue to work.

## Provider references

The NVIDIA CSV query follows [NVIDIA's monitoring examples](https://nvidia.custhelp.com/app/answers/detail/a_id/3751/~/useful-nvidia-smi-queries). Intel CSV fields and version requirements follow the [Intel XPU-SMI 2.0 command documentation](https://intel.github.io/xpumanager/2.0/xpu-smi/overview.html). AMD Linux file units are documented in the [AMDgpu kernel driver reference](https://dri.freedesktop.org/docs/drm/gpu/amdgpu.html).
