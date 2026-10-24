# SpectralSensor.py
# Driver for the AS7262 and AS7341 spectral colour sensors operating over I2C

import time
import sys

def initialise_as7262():
    import qwiic_as726x
    sensor = qwiic_as726x.QwiicAS726x()
    if not sensor.begin():
        raise RuntimeError("AS7262 not detected. Check your I2C wiring.")
    print("AS7262 initialised successfully.")
    return sensor

def capture_as7262_data(sensor, num_readings=10):
    print(f"Illuminating sample and taking {num_readings} measurements...")
    
    # Set to lowest 12.5mA current and turn on the illumination LED
    sensor.set_bulb_current(0)
    sensor.enable_bulb()
    time.sleep(0.2)
    
    data = {key: [] for key in [
        "timestamp", "450nm_Violet", "500nm_Blue", "550nm_Green", 
        "570nm_Yellow", "600nm_Orange", "650nm_Red"
    ]}
    
    for _ in range(num_readings):
        sensor.take_measurements()
        data["timestamp"].append(time.time())
        data["450nm_Violet"].append(sensor.get_calibrated_violet())
        data["500nm_Blue"].append(sensor.get_calibrated_blue())
        data["550nm_Green"].append(sensor.get_calibrated_green())
        data["570nm_Yellow"].append(sensor.get_calibrated_yellow())
        data["600nm_Orange"].append(sensor.get_calibrated_orange())
        data["650nm_Red"].append(sensor.get_calibrated_red())
        
    # Turn off the LED to prevent heat buildup on the samples
    sensor.disable_bulb()
        
    return data

def initialise_as7341():
    import board
    import adafruit_as7341
    i2c = board.I2C()
    sensor = adafruit_as7341.AS7341(i2c)
    print("AS7341 initialised successfully.")
    return sensor

def capture_as7341_data(sensor, num_readings=10):
    print(f"Illuminating sample and taking {num_readings} measurements...")
    
    data = {key: [] for key in [
        "timestamp", "415nm_F1", "445nm_F2", "480nm_F3", "515nm_F4", 
        "555nm_F5", "590nm_F6", "630nm_F7", "680nm_F8", "Clear", "NIR"
    ]}
    
    sensor.led_current = 10
    sensor.led = True
    time.sleep(0.2)
    
    for _ in range(num_readings):
        data["timestamp"].append(time.time())
        data["415nm_F1"].append(sensor.channel_415nm)
        data["445nm_F2"].append(sensor.channel_445nm)
        data["480nm_F3"].append(sensor.channel_480nm)
        data["515nm_F4"].append(sensor.channel_515nm)
        data["555nm_F5"].append(sensor.channel_555nm)
        data["590nm_F6"].append(sensor.channel_590nm)
        data["630nm_F7"].append(sensor.channel_630nm)
        data["680nm_F8"].append(sensor.channel_680nm)
        data["Clear"].append(sensor.channel_clear)
        data["NIR"].append(sensor.channel_nir)
        
    sensor.led = False
    return data

if __name__ == '__main__':
    print("Select the connected spectral sensor:")
    print("1: AS7262 (6-Channel)")
    print("2: AS7341 (10-Channel)")
    
    choice = input("Enter 1 or 2: ").strip()
    
    if choice not in ['1', '2']:
        print("Invalid selection. Exiting.")
        sys.exit(1)

    try:
        if choice == '1':
            sensor = initialise_as7262()
            readings = capture_as7262_data(sensor)
        else:
            sensor = initialise_as7341()
            readings = capture_as7341_data(sensor)
            
        for wavelength, values in readings.items():
            if wavelength != "timestamp":
                # Formats the list of floats to 2 decimal places for readable output
                formatted_values = [f"{float(v):.2f}" for v in values]
                print(f"  {wavelength}: {formatted_values}")

    except Exception as e:
        print(f"Error: {e}")