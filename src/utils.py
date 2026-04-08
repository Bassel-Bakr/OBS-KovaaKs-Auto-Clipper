import sys
import time
from pathlib import Path


def get_creation_or_modification_time(path: Path):
    """
    Gets the best available timestamp for the given file path, depending on the platform.
    """
    stat = path.stat()

    if sys.platform.startswith("win"):
        return stat.st_ctime
    elif sys.platform == "darwin":
        return stat.st_birthtime
    else:
        # Better than ctime on Linux
        return stat.st_mtime


def wait_until_ready(path: Path, timeout: int = 5) -> bool:
    """
    Waits until the file at the given path is ready (i.e., can be opened without error).
    """
    start = time.time()
    while True:
        try:
            with open(path, "rb"):
                return True
        except:
            if time.time() - start > timeout:
                return False
            time.sleep(0.2)


def wait_until_stable(
    path: Path, poll_interval: float = 0.2, stable_checks: int = 3
) -> None:
    """
    Waits until the file at 'path' exists and its size is stable for a few checks.
    """
    checks = 0
    last_size = -1
    while checks < stable_checks:
        if not path.exists():
            checks = 0
            time.sleep(poll_interval)
            continue
        size = path.stat().st_size
        if size == last_size:
            checks += 1
        else:
            checks = 0
        last_size = size
        time.sleep(poll_interval)
