from dataclasses import dataclass
@dataclass(kw_only=True)
class LedDrivingSettings:
    """Parameters for one TLC5940 output channel."""
    tlc5940_channel: int
    drive_current_ma: float