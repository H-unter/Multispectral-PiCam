# config.py
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

from models import CameraSettings, LEDAttributes, LedDrivingSettings, SpectralChannel, SpectralChannelCollection


@dataclass(frozen=True)
class CameraDefinition:
    """Represents the input parameters required to define a camera in the system"""
    camera_id: str
    csi_port: int
    label: str

DEFAULT_CAMERA_SETTINGS = CameraSettings(
    ae_enable=True,
    awb_enable=True,
    af_mode=0,
    lens_position=10.0
)

CAMERA_CONFIG = [
    CameraDefinition(
        camera_id="noir",
        csi_port=2,
        label="NoIR camera (imx708_noir)",
    ),
]

# convenient object for which to define the LEDs we have, and call it more sussinctly in SpectralChannelCollection
LED_name_to_LEDAttributes = {
   'red_led': LEDAttributes(model_number='unknown', peak_wavelength_nm=620.0,min_wavelength_nm=510.0, max_wavelength_nm=530.0, max_current_ma=20, viewing_angle_deg=120, datasheet_url= "unknown"),
   'green_led': LEDAttributes(model_number='unknown', peak_wavelength_nm=520.0, min_wavelength_nm=510.0, max_wavelength_nm=530.0, max_current_ma=20, viewing_angle_deg=120, datasheet_url= "unknown"),
}

SPECTRAL_CHANNELS = SpectralChannelCollection([
    SpectralChannel(
        name=f"red_led_{tlc5940_channel}",
        led=LED_name_to_LEDAttributes['red_led'],
        driver=LedDrivingSettings(tlc5940_channel=tlc5940_channel, drive_current_ma=20),
        camera=CameraSettings(exposure_time_us=60000)
    )
    for tlc5940_channel in range(16)
])

DEFAULT_CHANNEL_CALIBRATION_PATH = Path(__file__).parent / "tuning" / "channel_calibration.json"


def apply_channel_calibration(
    calibration_path: str | Path,
    channels: SpectralChannelCollection = SPECTRAL_CHANNELS,
) -> dict[str, int]:
    """Apply exposure settings from a tuning JSON artifact to channel config."""
    path = Path(calibration_path)
    with path.open("r", encoding="utf-8") as calibration_file:
        calibration: Any = json.load(calibration_file)

    if not isinstance(calibration, dict):
        raise ValueError(f"Calibration file {path} must contain a JSON object")
    if calibration.get("schema_version") != 1:
        raise ValueError(f"Unsupported calibration schema in {path}")
    if calibration.get("target_metric") != "mean_monochrome_intensity":
        raise ValueError(f"Unsupported calibration metric in {path}")

    channel_results = calibration.get("channels")
    if not isinstance(channel_results, dict):
        raise ValueError(f"Calibration file {path} has no channel results")

    configured_names = {channel.name for channel in channels}
    calibration_names = set(channel_results)
    missing_names = configured_names - calibration_names
    unknown_names = calibration_names - configured_names
    if missing_names or unknown_names:
        raise ValueError(
            f"Calibration channels do not match config; "
            f"missing={sorted(missing_names)}, unknown={sorted(unknown_names)}"
        )

    applied: dict[str, int] = {}
    for channel in channels:
        result = channel_results[channel.name]
        exposure = result.get("exposure_time_us") if isinstance(result, dict) else None
        if isinstance(exposure, bool) or not isinstance(exposure, (int, float)):
            raise ValueError(
                f"Calibration exposure for {channel.name} is not numeric"
            )
        if not math.isfinite(exposure) or exposure <= 0:
            raise ValueError(
                f"Calibration exposure for {channel.name} must be positive"
            )
        exposure_us = int(round(exposure))
        channel.camera.exposure_time_us = exposure_us
        applied[channel.name] = exposure_us

    return applied


if __name__ == "__main__":
    # Print the channel collection for verification
    print(SPECTRAL_CHANNELS)