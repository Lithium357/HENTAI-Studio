"""Real standalone server plus an external trainer for browser acceptance tests."""

import json
import os
import socket
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import uvicorn
from hentai_studio.api.app import create_app

with TemporaryDirectory(
    dir=os.environ.get("STUDIO_TEST_TMP"), prefix="studio-browser-"
) as temporary:
    app = create_app(Path(temporary) / "workspace")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    print(
        json.dumps(
            {
                "port": sock.getsockname()[1],
                "root": str(Path(__file__).parents[2].resolve()),
                "python": sys.executable,
            }
        ),
        flush=True,
    )
    uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[sock])
