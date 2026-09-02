from __future__ import annotations

import ctypes
import subprocess
import time


class PowerService:
    def lock(self) -> dict[str, str | bool]:
        if not ctypes.windll.user32.LockWorkStation():
            raise RuntimeError("Windows refused to lock the workstation")
        return {"success": True, "message": "Laptop locked"}

    def sleep(self, delay: float = 0.8) -> None:
        time.sleep(delay)
        # False, True, False = sleep, force, no wakeup events restriction
        result = ctypes.windll.powrprof.SetSuspendState(False, True, False)
        if result == 0:
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Add-Type -AssemblyName System.Windows.Forms; "
                    "[System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $true)",
                ],
                check=False,
            )

    def restart(self, delay: float = 1.0) -> None:
        time.sleep(delay)
        subprocess.run(["shutdown", "/r", "/t", "0", "/f"], check=False)

    def shutdown(self, delay: float = 1.0) -> None:
        time.sleep(delay)
        subprocess.run(["shutdown", "/s", "/t", "0", "/f"], check=False)
