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
    awb_enable=False,
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
#    'red_led': LEDAttributes(model_number='unknown', peak_wavelength_nm=620.0,min_wavelength_nm=510.0, max_wavelength_nm=530.0, max_current_ma=20, viewing_angle_deg=120, datasheet_url= "unknown"),
#    'red_led_little': LEDAttributes(model_number='unknown', peak_wavelength_nm=620.0,min_wavelength_nm=510.0, max_wavelength_nm=530.0, max_current_ma=12, viewing_angle_deg=120, datasheet_url= "unknown"),
#    'green_led': LEDAttributes(model_number='unknown', peak_wavelength_nm=520.0, min_wavelength_nm=510.0, max_wavelength_nm=530.0, max_current_ma=20, viewing_angle_deg=120, datasheet_url= "unknown"),
    
    'MT51020-IR': LEDAttributes(
        model_number='MT51020-IR', peak_wavelength_nm=1020.0, min_wavelength_nm=1000.0, max_wavelength_nm=1050.0, max_current_ma=100, viewing_angle_deg=40, datasheet_url="https://www.digikey.com.au/en/products/detail/marktech-optoelectronics/MT51020-IR/7319592"
    ),
    'MTE9460C2': LEDAttributes(
        model_number='MTE9460C2', peak_wavelength_nm=950.0, min_wavelength_nm=930.0, max_wavelength_nm=970.0, max_current_ma=100, viewing_angle_deg=120, datasheet_url="https://www.digikey.com.au/en/products/detail/marktech-optoelectronics/MTE9460C2/4249229"
    ),
    'XTHI30W': LEDAttributes(
        model_number='XTHI30W', peak_wavelength_nm=880.0, min_wavelength_nm=860.0, max_wavelength_nm=910.0, max_current_ma=50, viewing_angle_deg=50, datasheet_url="https://www.digikey.com.au/en/products/detail/sunled/XTHI30W/4745875"
    ),
    'SFH_4356': LEDAttributes(
        model_number='SFH 4356', peak_wavelength_nm=860.0, min_wavelength_nm=837.0, max_wavelength_nm=870.0, max_current_ma=100, viewing_angle_deg=20, datasheet_url="https://www.digikey.com.au/en/products/detail/ams-osram-ag/SFH-4356/5719269"
    ),
    'MTE1081C': LEDAttributes(
        model_number='MTE1081C', peak_wavelength_nm=810.0, min_wavelength_nm=790.0, max_wavelength_nm=820.0, max_current_ma=60, viewing_angle_deg=50, datasheet_url="https://www.digikey.com.au/en/products/detail/marktech-optoelectronics/MTE1081C/3516612 "
    ),
    'MTE2077N1-R': LEDAttributes(
        model_number='MTE2077N1-R', peak_wavelength_nm=765.0, min_wavelength_nm=745.0, max_wavelength_nm=780.0, max_current_ma=50, viewing_angle_deg=16, datasheet_url="https://www.digikey.com.au/en/products/detail/marktech-optoelectronics/MTE2077N1-R/4249222"
    ),
    'MTE1074N1-R': LEDAttributes(
        model_number='MTE1074N1-R', peak_wavelength_nm=740.0, min_wavelength_nm=725.0, max_wavelength_nm=755.0, max_current_ma=50, viewing_angle_deg=24, datasheet_url="https://www.digikey.com.au/en/products/detail/marktech-optoelectronics/MTE1074N1-R/3516610"
    ),
    'MTE6800N2-UR': LEDAttributes(
        model_number='MTE6800N2-UR', peak_wavelength_nm=680.0, min_wavelength_nm=670.0, max_wavelength_nm=690.0, max_current_ma=50, viewing_angle_deg=70, datasheet_url="https://www.digikey.com.au/en/products/detail/marktech-optoelectronics/MTE6800N2-UR/3516608"
    ),
    'MTE7063C2-UR': LEDAttributes(
        model_number='MTE7063C2-UR', peak_wavelength_nm=640.0, min_wavelength_nm=630.0, max_wavelength_nm=655.0, max_current_ma=50, viewing_angle_deg=100, datasheet_url="https://www.digikey.com.au/en/products/detail/marktech-optoelectronics/MTE7063C2-UR/8566061 "
    ),
    'BL-B8141-TRS20A': LEDAttributes(
        model_number='BL-B8141-TRS20A', peak_wavelength_nm=606.0, min_wavelength_nm=588.5, max_wavelength_nm=623.5, max_current_ma=20, viewing_angle_deg=35, datasheet_url="https://www.digikey.com.au/en/products/detail/american-bright-optoelectronics-corporation/BL-B8141-TRS20A/22486924"
    ),
    '151031VS06000': LEDAttributes(
        model_number='151031VS06000', peak_wavelength_nm=568.0, min_wavelength_nm=549.0, max_wavelength_nm=575.0, max_current_ma=20, viewing_angle_deg=60, datasheet_url="https://www.digikey.com.au/en/products/detail/w%C3%BCrth-elektronik/151031VS06000/4489988 "
    ),
    'XSCGS43MB': LEDAttributes(
        model_number='XSCGS43MB', peak_wavelength_nm=505.0, min_wavelength_nm=487.5, max_wavelength_nm=522.5, max_current_ma=20, viewing_angle_deg=110, datasheet_url="https://www.digikey.com.au/en/products/detail/sunled/XSCGS43MB/4745854"
    ),
    'WP710A10QBC-D': LEDAttributes(
        model_number='WP710A10QBC/D', peak_wavelength_nm=460.0, min_wavelength_nm=447.5, max_wavelength_nm=472.5, max_current_ma=20, viewing_angle_deg=20, datasheet_url="https://www.digikey.com.au/en/products/detail/kingbright/WP710A10QBC-D/2769812"
    ),
    'MT0380-UV-A': LEDAttributes(
        model_number='MT0380-UV-A', peak_wavelength_nm=400.0, min_wavelength_nm=390.0, max_wavelength_nm=405.0, max_current_ma=30, viewing_angle_deg=30, datasheet_url="https://www.digikey.com.au/en/products/detail/marktech-optoelectronics/MT0380-UV-A/4214613"
    ),
    'VAOL-5GUV8T4': LEDAttributes(
        model_number='VAOL-5GUV8T4', peak_wavelength_nm=385.0, min_wavelength_nm=360.0, max_wavelength_nm=400.0, max_current_ma=30, viewing_angle_deg=60, datasheet_url="https://www.digikey.com.au/en/products/detail/visual-communications-company-vcc/VAOL-5GUV8T4/4515709"
    )
}

SPECTRAL_CHANNELS = SpectralChannelCollection([
    SpectralChannel(
        name="0_1020nm_IR",
        led=LED_name_to_LEDAttributes['MT51020-IR'],
        driver=LedDrivingSettings(tlc5940_channel=0, drive_current_ma=10),
        camera=CameraSettings(exposure_time_us=60000)
    ),
    SpectralChannel(
        name="1_950nm_IR",
        led=LED_name_to_LEDAttributes['MTE9460C2'],
        driver=LedDrivingSettings(tlc5940_channel=1, drive_current_ma=10),
        camera=CameraSettings(exposure_time_us=60000)
    ),
    SpectralChannel(
        name="2_880nm_IR",
        led=LED_name_to_LEDAttributes['XTHI30W'],
        driver=LedDrivingSettings(tlc5940_channel=2, drive_current_ma=10),
        camera=CameraSettings(exposure_time_us=60000)
    ),
    SpectralChannel(
        name="3_860nm_IR",
        led=LED_name_to_LEDAttributes['SFH_4356'],
        driver=LedDrivingSettings(tlc5940_channel=3, drive_current_ma=10),
        camera=CameraSettings(exposure_time_us=60000)
    ),
    SpectralChannel(
        name="4_810nm_IR",
        led=LED_name_to_LEDAttributes['MTE1081C'],
        driver=LedDrivingSettings(tlc5940_channel=4, drive_current_ma=10),
        camera=CameraSettings(exposure_time_us=60000)
    ),
    SpectralChannel(
        name="5_765nm_IR",
        led=LED_name_to_LEDAttributes['MTE2077N1-R'],
        driver=LedDrivingSettings(tlc5940_channel=5, drive_current_ma=10),
        camera=CameraSettings(exposure_time_us=60000)
    ),
    SpectralChannel(
        name="6_740nm_IR",
        led=LED_name_to_LEDAttributes['MTE1074N1-R'],
        driver=LedDrivingSettings(tlc5940_channel=6, drive_current_ma=10),
        camera=CameraSettings(exposure_time_us=60000)
    ),
    SpectralChannel(
        name="7_680nm_R",
        led=LED_name_to_LEDAttributes['MTE6800N2-UR'],
        driver=LedDrivingSettings(tlc5940_channel=7, drive_current_ma=10),
        camera=CameraSettings(exposure_time_us=60000)
    ),
    SpectralChannel(
        name="8_640nm_R",
        led=LED_name_to_LEDAttributes['MTE7063C2-UR'],
        driver=LedDrivingSettings(tlc5940_channel=8, drive_current_ma=10),
        camera=CameraSettings(exposure_time_us=60000)
    ),
    SpectralChannel(
        name="9_606nm_R",
        led=LED_name_to_LEDAttributes['BL-B8141-TRS20A'],
        driver=LedDrivingSettings(tlc5940_channel=9, drive_current_ma=10),
        camera=CameraSettings(exposure_time_us=60000)
    ),
    SpectralChannel(
        name="10_568nm_G",
        led=LED_name_to_LEDAttributes['151031VS06000'],
        driver=LedDrivingSettings(tlc5940_channel=10, drive_current_ma=10),
        camera=CameraSettings(exposure_time_us=60000)
    ),
    SpectralChannel(
        name="11_505nm_G",
        led=LED_name_to_LEDAttributes['XSCGS43MB'],
        driver=LedDrivingSettings(tlc5940_channel=11, drive_current_ma=10),
        camera=CameraSettings(exposure_time_us=60000)
    ),
    SpectralChannel(
        name="12_460nm_B",
        led=LED_name_to_LEDAttributes['WP710A10QBC-D'],
        driver=LedDrivingSettings(tlc5940_channel=12, drive_current_ma=10),
        camera=CameraSettings(exposure_time_us=60000)
    ),
    SpectralChannel(
        name="13_400nm_UV",
        led=LED_name_to_LEDAttributes['MT0380-UV-A'],
        driver=LedDrivingSettings(tlc5940_channel=13, drive_current_ma=10),
        camera=CameraSettings(exposure_time_us=60000)
    ),
    SpectralChannel(
        name="14_385nm_UV",
        led=LED_name_to_LEDAttributes['VAOL-5GUV8T4'],
        driver=LedDrivingSettings(tlc5940_channel=14, drive_current_ma=10),
        camera=CameraSettings(exposure_time_us=60000)
    ),
    # RESERVED FOR THE WHITE CHANNEL
    # SpectralChannel(
    #     name="red_led_15",
    #     led=LED_name_to_LEDAttributes['red_led'],
    #     driver=LedDrivingSettings(tlc5940_channel=15, drive_current_ma=20),
    #     camera=CameraSettings(exposure_time_us=60000)
    # )
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