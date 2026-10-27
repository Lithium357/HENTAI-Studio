"""Signals are sent only to verified process identities owned by a job."""

import psutil


def verified_process(pid, created):
    if not pid or not created:
        return None
    try:
        process = psutil.Process(pid)
        if (
            process.is_running()
            and abs(process.create_time() - created) < 0.01
            and process.status() != psutil.STATUS_ZOMBIE
        ):
            return process
    except psutil.NoSuchProcess:
        pass
    return None


def terminate_tree(process, timeout=5):
    try:
        owned = process.children(recursive=True) + [process]
    except psutil.NoSuchProcess:
        return
    # Process objects cache their creation time before signals, protecting reused PIDs.
    for child in owned:
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(owned, timeout=timeout)
    for child in alive:
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(alive, timeout=timeout)
