#SpectralSensor.py
# driver for the AS726x spectral sensor operating over I2C

import time
import qwiic_as726x

def initialize_sensor():
    """Initializes the AS7262 sensor and returns the sensor object."""
    sensor = qwiic_as726x.QwiicAS726x()
    
    if not sensor.begin():
        raise RuntimeError("AS7262 not detected. Check your I2C wiring and ensure I2C is enabled.")
    
    # The sensor defaults to One-Shot mode (Mode 3) which is perfect for controlled captures.
    print("AS7262 initialized successfully.")
    return sensor

def capture_spectral_data(sensor):
    """Triggers a reading and returns a dictionary of the calibrated 6-channel data."""
    print("Taking measurement...")
    sensor.take_measurements() # Triggers the conversion cycle
    
    # Fetch calibrated float values
    data = {
        "timestamp": time.time(),
        "450nm_Violet": sensor.get_calibrated_violet(),
        "500nm_Blue": sensor.get_calibrated_blue(),
        "550nm_Green": sensor.get_calibrated_green(),
        "570nm_Yellow": sensor.get_calibrated_yellow(),
        "600nm_Orange": sensor.get_calibrated_orange(),
        "650nm_Red": sensor.get_calibrated_red()
    }
    return data

if __name__ == '__main__':
   try:
      as7262 = initialize_sensor()
      readings = capture_spectral_data(as7262)
      for wavelength, value in readings.items():
         if wavelength != "timestamp":
            print(f"  {wavelength}: {value:.2f}")

   except Exception as e:
      print(f"Error: {e}")