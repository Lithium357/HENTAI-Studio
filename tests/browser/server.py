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
    checkpoint = Path(temporary) / "demo-checkpoint"
    if os.environ.get("STUDIO_BROWSER_LLM"):
        checkpoint.mkdir()
        (checkpoint / "config.json").write_text("{}")
        runner = Path(temporary) / "fake-infer.py"
        runner.write_text(
            "import sys,json\nconfig=json.loads(sys.stdin.readline())\nprint(json.dumps({'ready':True}),flush=True)\nfor line in sys.stdin:\n request=json.loads(line)\n print(json.dumps({'content':'Local scratch reply: '+request['messages'][-1]['content'],'tokens':5}),flush=True)\n"
        )
        app.state.chat.runner = runner
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    print(
        json.dumps(
            {
                "port": sock.getsockname()[1],
                "root": str(Path(__file__).parents[2].resolve()),
                "python": sys.executable,
                "checkpoint": str(checkpoint),
            }
        ),
        flush=True,
    )
    uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[sock])
