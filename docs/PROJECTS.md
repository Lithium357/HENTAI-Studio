# Projects and jobs

## Connect a project

Register an ID, display name, absolute project directory and named commands as JSON argument arrays:

```json
{
  "train": ["/absolute/project/.venv/bin/python", "-u", "train.py", "--output", "{output_dir}"],
  "evaluate": ["/absolute/project/.venv/bin/python", "evaluate.py", "--output", "{output_dir}"]
}
```

Use the project's own executable and real flags. Studio executes each array directly, without a shell, in the registered directory. It doesn't activate environments, install project dependencies, guess checkpoint locations or modify project configs. Windows executables and paths work the same way; backslashes must be escaped inside JSON strings.

Commands and configured environment values support `{project_root}` and `{output_dir}` substitutions. Trainers receive:

| Variable | Meaning |
| --- | --- |
| `STUDIO_OUTPUT_DIR` | New job's absolute output directory |
| `STUDIO_JOB_ID` | Unique job ID |
| `STUDIO_PROJECT_ID` | Registered project ID |
| `STUDIO_RESUME_DIR` | Previous job's output directory, only when a resume source is selected |

Write checkpoints and other downloadable files into the supplied output directory. A small wrapper owned by the training project can adapt existing config/output conventions. Commands that write elsewhere still run and stream logs; their external outputs aren't automatically imported.

To plot metrics, write numeric newline-terminated JSONL records to `metrics.jsonl`, or configure a relative `.csv`/`.jsonl` path:

```json
{"step": 1, "loss": 2.1, "accuracy": 0.6}
{"step": 2, "loss": 1.8, "accuracy": 0.7}
```

Any numeric column can be plotted. Metrics are optional. [examples/project.json](../examples/project.json) is a registration template; [examples/demo_train.py](../examples/demo_train.py) is a standard-library demo with checkpoints, metrics and resume. Register this repository and use your Python executable followed by `examples/demo_train.py` to try it without a model.


## Manage jobs

Each project can have one active job, while independent projects can run concurrently. Every job snapshots its command/configuration and owns separate output and console files. Dashboard shutdown leaves supervisors running; reopen the same workspace to reconnect.

Stop terminates the selected trainer tree. It does not guarantee a checkpoint. Resume starts a new job using your chosen command and supplies `STUDIO_RESUME_DIR`; your trainer chooses what to restore.

If a supervisor dies, Studio marks the job interrupted and checks recorded process identities. Verified survivors remain stoppable and block another launch for that project. Older jobs created before process identities were recorded may require manual inspection; Studio won't guess or signal an unverified PID.

**All jobs** preserves access to history after a project is unregistered. Unregistration removes only its definition. Project files and job outputs stay on disk. Broken workspace records are reported visibly; valid history stays readable, and launches/registration changes are blocked until the damaged records are repaired.

