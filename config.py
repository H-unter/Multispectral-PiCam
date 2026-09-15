# config.py
from models import CameraSettings, LEDAttributes, LedDrivingSettings, SpectralChannel

DEFAULT_CAMERA_SETTINGS = CameraSettings(
    ae_enable=True,
    awb_enable=True,
    af_mode=0,
    lens_position=10.0
)
CHANNELS = [
    SpectralChannel(
        name="LED 1 (UV)",
        led=LEDAttributes(model_number="UV-365", peak_wavelength_nm=365, min_wavelength_nm=360, max_wavelength_nm=370, max_current_ma=1000, viewing_angle_deg=120, datasheet_url=""),
        driver=LedDrivingSettings(gpio_pin=17, drive_current_ma=500),
        camera=CameraSettings(exposure_time_us=1000000, analogue_gain=1.0)
    ),
    SpectralChannel(
        name="LED 2 (Blue)",
        led=LEDAttributes(model_number="BL-450", peak_wavelength_nm=450, min_wavelength_nm=440, max_wavelength_nm=460, max_current_ma=1000, viewing_angle_deg=120, datasheet_url=""),
        driver=LedDrivingSettings(gpio_pin=27, drive_current_ma=500),
        camera=CameraSettings(exposure_time_us=1000000, analogue_gain=1.0)
    ),
    SpectralChannel(
        name="Dark Frame",
        led=None, # No LED for dark frame
        driver=LedDrivingSettings(gpio_pin=None, drive_current_ma=0),
        camera=CameraSettings(exposure_time_us=1000000, analogue_gain=1.0)
    )
]