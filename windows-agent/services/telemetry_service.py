from __future__ import annotations

import time
from typing import Any

import psutil

from config.settings import settings


class TelemetryService:
    def __init__(self) -> None:
        self._gpu_ready = False
        self._nvml = None
        self._init_gpu()

    def _init_gpu(self) -> None:
        try:
            import pynvml

            pynvml.nvmlInit()
            self._nvml = pynvml
            self._gpu_ready = True
        except Exception:
            self._gpu_ready = False
            self._nvml = None

    def health(self, device_id: str, authenticated: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": "online",
            "agent_version": settings.agent_version,
        }
        if authenticated:
            payload["device_id"] = device_id
        return payload

    def status(self, device_name: str) -> dict[str, Any]:
        cpu_percent = psutil.cpu_percent(interval=0.25)
        memory = psutil.virtual_memory()
        battery = psutil.sensors_battery()
        gpu = self._gpu()
        thermal = self._cpu_temp()

        return {
            "device_name": device_name,
            "online": True,
            "cpu_percent": round(cpu_percent, 1),
            "ram_percent": round(memory.percent, 1),
            "ram_used_gb": round(memory.used / (1024**3), 1),
            "ram_total_gb": round(memory.total / (1024**3), 1),
            "battery_percent": None if battery is None else round(battery.percent),
            "charging": None if battery is None else bool(battery.power_plugged),
            "uptime_seconds": int(time.time() - psutil.boot_time()),
            "gpu_percent": gpu.get("gpu_percent"),
            "gpu_temp_c": gpu.get("gpu_temp_c"),
            "cpu_temp_c": thermal,
        }

    def _gpu(self) -> dict[str, Any]:
        empty = {"gpu_percent": None, "gpu_temp_c": None}
        if not self._gpu_ready or self._nvml is None:
            return empty
        try:
            handle = self._nvml.nvmlDeviceGetHandleByIndex(0)
            util = self._nvml.nvmlDeviceGetUtilizationRates(handle)
            temp = self._nvml.nvmlDeviceGetTemperature(handle, self._nvml.NVML_TEMPERATURE_GPU)
            return {"gpu_percent": int(util.gpu), "gpu_temp_c": int(temp)}
        except Exception:
            return empty

    def _cpu_temp(self) -> float | None:
        try:
            import wmi

            client = wmi.WMI(namespace="root\\wmi")
            zones = client.MSAcpi_ThermalZoneTemperature()
            temps = []
            for zone in zones:
                kelvin_tenths = getattr(zone, "CurrentTemperature", None)
                if kelvin_tenths:
                    celsius = (kelvin_tenths / 10.0) - 273.15
                    if 0 < celsius < 120:
                        temps.append(celsius)
            if temps:
                return round(max(temps), 1)
        except Exception:
            return None
        return None
