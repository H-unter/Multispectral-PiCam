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
        controls = {}
        if self.exposure_time_us is not None:
            controls["ExposureTime"] = int(round(self.exposure_time_us))
        if self.analogue_gain is not None:
            controls["AnalogueGain"] = float(self.analogue_gain)
        if self.ae_enable is not None:
            controls["AeEnable"] = bool(self.ae_enable)
        if self.awb_enable is not None:
            controls["AwbEnable"] = bool(self.awb_enable)
        if self.af_mode is not None:
            controls["AfMode"] = int(self.af_mode)
        if self.lens_position is not None:
            controls["LensPosition"] = float(self.lens_position)
        if self.colour_gains is not None:
            controls["ColourGains"] = tuple(
                float(gain) for gain in self.colour_gains
            )
        return controls