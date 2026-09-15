from dataclasses import dataclass
from typing import Optional

@dataclass(kw_only=True)
class CameraSettings:
    """Object representing the required parameters for a camera capture"""
    exposure_time_us: Optional[int] = None # Exposure Time in microseconds
    analogue_gain: Optional[float] = None # Analogue Gain
    ae_enable: Optional[bool] = None # Auto Exposure
    awb_enable: Optional[bool] = None # Auto White Balance
    af_mode: Optional[int] = None # Auto Focus
    lens_position: Optional[float] = None # Lens Position
    colour_gains: Optional[tuple[float, float]] = None # Colour Gains

    def to_control_dict(self) -> dict:
        """Translates the dataclass into a Picamera2-compatible dictionary."""
        mapping = {
            "exposure_time_us": "ExposureTime",
            "analogue_gain": "AnalogueGain",
            "ae_enable": "AeEnable",
            "awb_enable": "AwbEnable",
            "af_mode": "AfMode",
            "lens_position": "LensPosition",
            "colour_gains": "ColourGains"
        }
        # Only return values that are explicitly set (not None)
        return {mapping[k]: v for k, v in self.__dict__.items() if v is not None}