"""Shared camera lock for rpicam-still contention prevention.

Usage:
    from camera_lock import camera_lock
    
    with camera_lock(timeout=10):
        subprocess.run(["rpicam-still", ...])
"""

import fcntl, os, time, contextlib

LOCK_FILE = "/tmp/rpicam.lock"

@contextlib.contextmanager
def camera_lock(timeout=10):
    """Acquire exclusive camera lock. Raises TimeoutError if can't acquire within timeout."""
    fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR)
    deadline = time.monotonic() + timeout
    acquired = False
    try:
        while time.monotonic() < deadline:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                time.sleep(0.5)
        if not acquired:
            raise TimeoutError(f"Could not acquire camera lock within {timeout}s")
        yield
    finally:
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
