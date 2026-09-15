from dataclasses import dataclass
from typing import Optional

from .LEDAttributes import LEDAttributes
from .LedDrivingSettings import LedDrivingSettings
from .CameraSettings import CameraSettings

@dataclass(kw_only=True)
class SpectralChannel:
    """A complete multispectral channel binding the LED, driver, and camera."""
    name: str
    led: Optional[LEDAttributes]  # Can be None for dark frames
    driver: LedDrivingSettings
    camera: CameraSettings