from dataclasses import dataclass
from typing import Optional

@dataclass(kw_only=True)
class LedDrivingSettings:
    """Object representing the parameters for driving the LED hardware."""
    gpio_pin: Optional[int]
    drive_current_ma: float