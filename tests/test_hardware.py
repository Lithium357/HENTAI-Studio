import subprocess
import threading
import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from hentai_studio.api.app import create_app
from hentai_studio.hardware import (
    MIB,
    GPUReading,
    HardwareMonitor,
    collect_gpus,
    linux_gpus,
    parse_smi,
)
from hentai_studio.hardware_windows import apply_counters


def test_smi_multiple_cards_and_unavailable_values():
    rows = parse_smi(
        'GPU-a,"NVIDIA, Test",0000:01:00.0,0,512,16384,42,80\nGPU-b,Second,0000:02:00.0,N/A,[Not Supported],32768,NaN,-1\n',
        "NVIDIA",
        "nvidia-smi",
    )
    assert len(rows) == 2 and rows[0].name == "NVIDIA, Test"
    assert rows[0].utilization_pct == 0 and rows[0].memory_total_mb == 16384
    assert rows[1].utilization_pct is None and rows[1].memory_used_mb is None
    assert rows[1].temperature_c is None and rows[1].power_w is None
    assert rows[0].id != rows[1].id
    intel = parse_smi(
        "intel-uuid,Intel Arc B580,0000:03:00.0,99,2048,12288,60,110",
        "Intel",
        "xpu-smi",
    )
    assert intel[0].vendor == "Intel" and intel[0].utilization_pct == 99


def test_linux_amd_intel_and_units(tmp_path):
    for index, vendor in enumerate(("0x1002", "0x8086")):
        device = tmp_path / f"card{index}" / "device"
        device.mkdir(parents=True)
        for name, value in {
            "vendor": vendor,
            "device": "0x1234",
            "gpu_busy_percent": "0",
            "mem_info_vram_used": str(2 * MIB),
            "mem_info_vram_total": str(16 * MIB),
        }.items():
            (device / name).write_text(value)
        sensor = device / "hwmon" / "hwmon0"
        sensor.mkdir(parents=True)
        (sensor / "temp1_input").write_text("45600")
        (sensor / "power1_average").write_text("123000000")
    (tmp_path / "card0-DP-1").mkdir()  # Connector nodes are not adapters.
    devices = linux_gpus(tmp_path)
    assert [gpu.vendor for gpu in devices] == ["AMD", "Intel"]
    assert devices[0].memory_used_mb == 2 and devices[0].memory_total_mb == 16
    assert devices[0].temperature_c == 45.6 and devices[0].power_w == 123
    assert devices[0].utilization_pct == 0
    (tmp_path / "card1/device/gpu_busy_percent").unlink()
    assert linux_gpus(tmp_path)[1].utilization_pct is None


def test_windows_vendor_neutral_counters_are_joined_by_luid():
    a, b = "luid_0x00000000_0x00000001", "luid_0x00000000_0x00000002"
    gpus = [
        GPUReading(id=a, vendor="AMD", name="Radeon", source="Windows"),
        GPUReading(id=b, vendor="Intel", name="Arc", source="Windows"),
    ]
    rows = {
        "engines": [
            {
                "Name": f"pid_1_{a}_phys_0_eng_0_engtype_Compute",
                "UtilizationPercentage": 60,
            },
            {
                "Name": f"pid_2_{a}_phys_0_eng_0_engtype_Compute",
                "UtilizationPercentage": 30,
            },
            {
                "Name": f"pid_1_{a}_phys_0_eng_1_engtype_Copy",
                "UtilizationPercentage": 80,
            },
            {"Name": f"pid_3_{b}_phys_0_eng_0_engtype_3D", "UtilizationPercentage": 0},
        ],
        "memory": [
            {"Name": a + "_phys_0", "DedicatedUsage": 8 * MIB, "SharedUsage": 2 * MIB}
        ],
    }
    apply_counters(gpus, rows)
    assert gpus[0].utilization_pct == 90  # Busiest engine; not 170% across engines.
    assert gpus[1].utilization_pct == 0
    assert gpus[0].memory_used_mb == 8 and gpus[0].shared_memory_mb == 2
    assert gpus[1].memory_used_mb is None
    assert gpus[0].temperature_c is None


def test_sampler_is_shared_nonblocking_and_marks_stale():
    called = threading.Event()
    release = threading.Event()

    def slow_gpu():
        called.set()
        release.wait(timeout=5)
        return [], ["No GPU visible"]

    monitor = HardwareMonitor(interval=0.01)
    try:
        with patch(
            "hentai_studio.hardware.collect_gpus", side_effect=slow_gpu
        ) as collect:
            assert monitor.snapshot().collecting
            assert called.wait(timeout=2)
            before = time.monotonic()
            for _ in range(20):
                assert monitor.snapshot().collecting
            assert time.monotonic() - before < 0.5
            assert collect.call_count == 1
            release.set()
            deadline = time.monotonic() + 2
            while monitor.snapshot().collecting and time.monotonic() < deadline:
                time.sleep(0.005)
            result = monitor.snapshot()
            assert result.sampled_at and result.cpu_pct is not None
            assert result.ram_total_mb > 0 and not result.stale
            result.issues.clear()
            assert monitor.snapshot().issues  # Callers cannot mutate the cache.
            monitor.close()
            monitor._thread.join(timeout=2)
            with monitor._lock:
                monitor._sample_time = time.monotonic() - 20
            assert monitor.snapshot().stale
    finally:
        monitor.close()
        release.set()


def test_provider_failure_preserves_other_gpus(monkeypatch):
    from hentai_studio import hardware

    monkeypatch.setattr(hardware.shutil, "which", lambda name: name)

    def provider(path, vendor):
        if vendor == "NVIDIA":
            raise subprocess.TimeoutExpired(path, 5)
        return [GPUReading(id="intel", name="Arc", vendor="Intel", source="xpu-smi")]

    monkeypatch.setattr(hardware, "smi_gpus", provider)
    with (
        patch("hentai_studio.hardware_windows.windows_gpus", return_value=([], [])),
        patch.object(hardware, "linux_gpus", return_value=[]),
    ):
        readings, issues = collect_gpus()
    assert readings[0].vendor == "Intel"
    assert any("TimeoutExpired" in issue for issue in issues)


def test_hardware_api_requires_no_jobs_and_client_helpers(tmp_path):
    app = create_app(tmp_path / "workspace", location="cloud")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get("/api/hardware")
        assert response.status_code == 200
        data = response.json()
        assert data["scope"] == "backend_host" and data["hostname"]
        assert data["collecting"] and data["sampled_at"] is None
        assert client.get("/api/jobs").json()["items"] == []
        assert "/api/hardware" in client.get("/api/openapi.json").json()["paths"]
    assert app.state.hardware._stop.is_set()
