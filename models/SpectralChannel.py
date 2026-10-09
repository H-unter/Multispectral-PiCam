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

    def __post_init__(self) -> None:
        """Reject channel configurations above the LED's safe current limit."""
        if (
            self.led is not None
            and self.driver.drive_current_ma > self.led.max_current_ma
        ):
            raise ValueError(
                f"Drive current for channel {self.name!r} "
                f"({self.driver.drive_current_ma:g} mA) exceeds the LED "
                f"maximum ({self.led.max_current_ma:g} mA)"
            )
