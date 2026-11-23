"""DXGI adapter identity + Windows GPU counters, independent of GPU vendor."""

import ctypes
import json
import re
import subprocess
import uuid
from ctypes import wintypes

from .hardware import MIB, GPUReading, command, number


def dxgi_adapters():
    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class Description(ctypes.Structure):
        _fields_ = [
            ("Description", ctypes.c_wchar * 128),
            ("VendorId", wintypes.UINT),
            ("DeviceId", wintypes.UINT),
            ("SubSysId", wintypes.UINT),
            ("Revision", wintypes.UINT),
            ("DedicatedVideoMemory", ctypes.c_size_t),
            ("DedicatedSystemMemory", ctypes.c_size_t),
            ("SharedSystemMemory", ctypes.c_size_t),
            ("AdapterLuid", LUID),
            ("Flags", wintypes.UINT),
        ]

    def method(pointer, index, *arguments):
        table = ctypes.cast(
            pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        ).contents
        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *arguments)(
            table[index]
        )

    factory = ctypes.c_void_p()
    iid = (ctypes.c_ubyte * 16).from_buffer_copy(
        uuid.UUID("770aae78-f26f-4dba-a829-253c83d1b387").bytes_le
    )
    create = ctypes.WinDLL("dxgi.dll").CreateDXGIFactory1
    create.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    create.restype = ctypes.c_long
    if create(ctypes.byref(iid), ctypes.byref(factory)) < 0:
        raise RuntimeError("DXGI initialization failed")
    result = []
    try:
        for index in range(64):
            adapter = ctypes.c_void_p()
            status = method(
                factory, 12, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)
            )(factory, index, ctypes.byref(adapter))
            if status < 0:
                break
            try:
                desc = Description()
                if (
                    method(adapter, 10, ctypes.POINTER(Description))(
                        adapter, ctypes.byref(desc)
                    )
                    < 0
                    or desc.Flags & 2
                ):
                    continue  # Software renderers are not physical GPUs.
                luid = f"luid_0x{desc.AdapterLuid.HighPart & 0xFFFFFFFF:08x}_0x{desc.AdapterLuid.LowPart:08x}"
                result.append(
                    GPUReading(
                        id=luid,
                        name=desc.Description,
                        vendor={0x10DE: "NVIDIA", 0x1002: "AMD", 0x8086: "Intel"}.get(
                            desc.VendorId, "Other"
                        ),
                        source="Windows GPU counters",
                        memory_total_mb=desc.DedicatedVideoMemory / MIB,
                    )
                )
            finally:
                method(adapter, 2)(adapter)
    finally:
        method(factory, 2)(factory)
    return result


COUNTERS = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$issues = @()
$engines = @(); $memory = @()
try { $engines = @(Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine | Select-Object Name,UtilizationPercentage) }
catch { $issues += 'GPU engine counters unavailable. A WDDM 2.x driver is required.' }
try { $memory = @(Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory | Select-Object Name,DedicatedUsage,SharedUsage) }
catch { $issues += 'GPU memory counters unavailable.' }
@{engines=$engines;memory=$memory;issues=$issues} | ConvertTo-Json -Depth 4 -Compress
"""


def apply_counters(adapters, counters):
    def identity(name):
        match = re.search(r"luid_0x[0-9a-f]+_0x[0-9a-f]+", name.lower())
        return match.group() if match else None

    engines = {}
    for row in counters.get("engines") or []:
        name = row.get("Name", "")
        luid = identity(name)
        # Sum processes on the same physical engine, then take the busiest engine.
        engine = re.search(r"phys_\d+_eng_\d+", name)
        usage = number(row.get("UtilizationPercentage"))
        if luid and engine and usage is not None:
            key = (luid, engine.group())
            engines[key] = engines.get(key, 0) + usage
    for adapter in adapters:
        usages = [value for (luid, _), value in engines.items() if luid == adapter.id]
        if usages:
            adapter.utilization_pct = min(100, max(usages))
        rows = [
            row
            for row in counters.get("memory") or []
            if identity(row.get("Name", "")) == adapter.id
        ]
        for field, target in (
            ("DedicatedUsage", "memory_used_mb"),
            ("SharedUsage", "shared_memory_mb"),
        ):
            values = [number(row.get(field)) for row in rows]
            if values and all(value is not None for value in values):
                setattr(adapter, target, sum(values) / MIB)
    return adapters


def windows_gpus():
    adapters = dxgi_adapters()
    try:
        counters = json.loads(
            command(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    COUNTERS,
                ],
                timeout=8,
            )
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return adapters, [
            f"Windows GPU counters: {type(error).__name__}; usage unavailable."
        ]
    return apply_counters(adapters, counters), counters.get("issues") or []
