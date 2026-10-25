"""A standard-library trainer to try Studio without ML dependencies."""
import argparse
import json
import os
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--steps", type=int, default=30)
parser.add_argument("--delay", type=float, default=.3)
args = parser.parse_args()
output = Path(os.environ["STUDIO_OUTPUT_DIR"])
output.mkdir(parents=True, exist_ok=True)
previous = os.environ.get("STUDIO_RESUME_DIR")
start = 0
if previous and (Path(previous) / "checkpoint.json").is_file():
    start = json.loads((Path(previous) / "checkpoint.json").read_text())["step"]
print(f"Training from step {start} into {output}", flush=True)
with (output / "metrics.jsonl").open("a", encoding="utf-8") as metrics:
    for step in range(start + 1, start + args.steps + 1):
        loss = 1 / (step ** .5)
        metrics.write(json.dumps({"step": step, "loss": loss, "accuracy": 1 - loss / 2}) + "\n")
        metrics.flush()
        (output / "checkpoint.json").write_text(json.dumps({"step": step}), encoding="utf-8")
        print(f"step={step} loss={loss:.4f}", flush=True)
        time.sleep(args.delay)
print("Finished", flush=True)
