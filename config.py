# config.py
from models import CameraSettings, LEDAttributes, LedDrivingSettings, SpectralChannel, SpectralChannelCollection

DEFAULT_CAMERA_SETTINGS = CameraSettings(
    ae_enable=True,
    awb_enable=True,
    af_mode=0,
    lens_position=10.0
)

LED_LOOKUP_TABLE = {
   'green_led': LEDAttributes(model_number='unknown', peak_wavelength_nm=520.0, min_wavelength_nm=510.0, max_wavelength_nm=530.0, max_current_ma=20, viewing_angle_deg=120, datasheet_url= "unknown"),
   'red_led_1': LEDAttributes(model_number='unknown', peak_wavelength_nm=620.0,min_wavelength_nm=510.0, max_wavelength_nm=530.0, max_current_ma=20, viewing_angle_deg=120, datasheet_url= "unknown"),
   'red_led_2': LEDAttributes(model_number='unknown', peak_wavelength_nm=620.0, min_wavelength_nm=510.0, max_wavelength_nm=530.0, max_current_ma=20, viewing_angle_deg=120, datasheet_url= "unknown")
}

SPECTRAL_CHANNELS = SpectralChannelCollection([
    SpectralChannel(
        name="green_led",
        led=LED_LOOKUP_TABLE['green_led'],
        driver=LedDrivingSettings(gpio_pin=17, drive_current_ma=500),
        camera=CameraSettings(exposure_time_us=1000000, analogue_gain=1.0)
    ),
    SpectralChannel(
        name="red_led_1",
        led=LED_LOOKUP_TABLE['red_led_1'],
        driver=LedDrivingSettings(gpio_pin=27, drive_current_ma=500),
        camera=CameraSettings(exposure_time_us=1000000, analogue_gain=1.0)
    ),
    SpectralChannel(
        name="red_led_2",
        led=LED_LOOKUP_TABLE['red_led_2'],
        driver=LedDrivingSettings(gpio_pin=22, drive_current_ma=500),
        camera=CameraSettings(exposure_time_us=1000000, analogue_gain=1.0)
    )
])


if __name__ == "__main__":
    # Print the channel collection for verification
    print(SPECTRAL_CHANNELS)