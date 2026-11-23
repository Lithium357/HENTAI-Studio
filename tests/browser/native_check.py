"""Run the Windows client checks against an isolated API fixture."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    executable = Path(sys.argv[1]).resolve()
    fixture = Path(__file__).with_name("native_fixture.py")
    with tempfile.TemporaryDirectory(prefix="studio-native-") as folder:
        log = Path(folder) / "requests.log"
        server = subprocess.Popen(
            [sys.executable, "-u", str(fixture), str(log)],
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            port = json.loads(server.stdout.readline())["port"]
            subprocess.run([str(executable), f"http://127.0.0.1:{port}/"], check=True)
            requests = log.read_text(encoding="utf-8").splitlines()
            assert requests and all(" /api/" in line for line in requests)
            print("Native client used JSON API routes only; no dashboard assets.")
        finally:
            server.terminate()
            server.wait(timeout=10)


if __name__ == "__main__":
    main()
