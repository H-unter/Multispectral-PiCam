# config.py
from dataclasses import dataclass

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
        name="red_led",
        led=LED_name_to_LEDAttributes['red_led'],
        driver=LedDrivingSettings(tlc5940_channel=0, drive_current_ma=17.8),
        camera=CameraSettings(exposure_time_us=10000, analogue_gain=1.0)
    ),
    SpectralChannel(
        name="green_led",
        led=LED_name_to_LEDAttributes['green_led'],
        driver=LedDrivingSettings(tlc5940_channel=1, drive_current_ma=17.8),
        camera=CameraSettings(exposure_time_us=10000, analogue_gain=1.0)
    ),
])


if __name__ == "__main__":
    # Print the channel collection for verification
    print(SPECTRAL_CHANNELS)