from __future__ import annotations

import io
from typing import Any

import pythoncom
from PIL import ImageGrab
from pycaw.pycaw import AudioUtilities


class MediaService:
    def _endpoint(self):
        pythoncom.CoInitialize()
        return AudioUtilities.GetSpeakers().EndpointVolume

    def volume(self) -> dict[str, Any]:
        endpoint = self._endpoint()
        scalar = float(endpoint.GetMasterVolumeLevelScalar())
        return {
            "volume_percent": int(round(max(0.0, min(1.0, scalar)) * 100)),
            "muted": bool(endpoint.GetMute()),
        }

    def set_volume(self, volume_percent: int | None, muted: bool | None) -> dict[str, Any]:
        endpoint = self._endpoint()
        if volume_percent is not None:
            endpoint.SetMasterVolumeLevelScalar(max(0, min(100, int(volume_percent))) / 100.0, None)
        if muted is not None:
            endpoint.SetMute(bool(muted), None)
        return self.volume()

    def screenshot_jpeg(self, quality: int = 55, max_width: int = 1280) -> bytes:
        image = ImageGrab.grab()
        if image.width > max_width:
            ratio = max_width / image.width
            image = image.resize((max_width, max(1, int(image.height * ratio))))
        if image.mode != "RGB":
            image = image.convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
        return buffer.getvalue()
