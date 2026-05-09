"""
VRChat process detection.
"""
import logging
import subprocess
import time

logger = logging.getLogger(__name__)

VRC_PROCESSES = ["VRChat.exe", "vrchat.exe"]


def is_vrchat_running() -> bool:
    """Check if VRChat process is running."""
    return _any_process_running(VRC_PROCESSES)


def get_vrchat_status() -> dict:
    """Get VRChat status."""
    vrc = is_vrchat_running()
    return {
        "vrchat_running": vrc,
        "ready": vrc,
        "message": "VRChat 已运行，可以启动翻译" if vrc else "等待 VRChat 启动... 请先打开 VRChat",
    }


def wait_for_vrchat(timeout: int = 0, callback=None) -> bool:
    """Wait for VRChat to start."""
    start = time.time()
    while True:
        if is_vrchat_running():
            logger.info("VRChat detected!")
            if callback:
                callback()
            return True
        if timeout > 0 and (time.time() - start) > timeout:
            return False
        if callback:
            callback()
        time.sleep(2)


def _any_process_running(process_names: list[str]) -> bool:
    """Check if any of the given processes are running (Windows)."""
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
        )
        output = result.stdout.lower()
        for name in process_names:
            if name.lower() in output:
                return True
        return False
    except Exception as e:
        logger.error(f"Process check failed: {e}")
        return False
