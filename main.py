#!/usr/bin/python3
import os
import sys
import numpy as np
import cv2  # Added for native BGR/JPG conversions
import time
from picamera2 import Picamera2
from dataclasses import dataclass
from contextlib import contextmanager
from gpiozero import LED

OUTPUT_DIR = "./images"
is_standard_capture_enabled = True

# Export mode configuration switch: "jpg", "array", or "hypercube"
EXPORT_MODE = "jpg"  

DEFAULT_CAMERA_SETTINGS = {
    "AeEnable": False,
    "AwbEnable": False,
    "ColourGains": (1.0, 1.0),
}

@dataclass
class LedAttributes:
    """Configuration settings for an optical band."""
    led: LED | None
    exposure_time_us: int
    analogue_gain: float

SPECTRAL_CONFIG = {
    "led1": {"pin": 17,   "exposure": 1000000, "gain": 1.0},
    "led2": {"pin": 27,   "exposure": 1000000, "gain": 1.0},
    "led3": {"pin": 22,   "exposure": 1000000, "gain": 1.0},
    "dark": {"pin": None, "exposure": 1000000, "gain": 1.0}
}

SPECTRAL_CHANNELS = {
    band: LedAttributes(
        led=LED(cfg["pin"]) if cfg["pin"] is not None else None,
        exposure_time_us=cfg["exposure"],
        analogue_gain=cfg["gain"]
    )
    for band, cfg in SPECTRAL_CONFIG.items()
}

@contextmanager
def switch_lighting(channel: LedAttributes):
    """Cleanly isolates the targeted wavelength LED or handles dark cycles."""
    if channel.led is not None:
        channel.led.on()
    else:
        print(" Isolating sensor environment (Dark Frame)...")
    try:
        yield
    finally:
        if channel.led is not None:
            channel.led.off()

def ensure_directory(path: str):
    if not os.path.exists(path):
        os.makedirs(path)

def acquire_standard_photo(camera: Picamera2, config) -> list[tuple[str, np.ndarray]]:
    print("Acquiring standard photo. Allowing ISP to meter the scene...")
    camera.set_controls({
        "AeEnable": True,
        "AwbEnable": True
    })
    time.sleep(1.5)     
    frame_array = camera.capture_array("main")
    return [("standard", frame_array)]

def acquire_spectral_cube(camera: Picamera2, config) -> list[tuple[str, np.ndarray]]:
    """
    RESPONSIBILITY: Pure Hardware Acquisition.
    Captures raw 3D arrays sequentially and maps them to their band names.
    """
    captured_layers = []
    try:
        for band, channel in SPECTRAL_CHANNELS.items():
            print(f"Acquiring spectral layer: [{band}]...")            
            with switch_lighting(channel):  
                camera.set_controls({
                    "ExposureTime": channel.exposure_time_us,
                    "AnalogueGain": channel.analogue_gain
                })
                # camera.switch_mode(config)
                
                # Fetch raw 3D array: (Height, Width, Channels)
                frame_array = camera.capture_array("main")
                captured_layers.append((band, frame_array))
        return captured_layers
    finally:
        camera.stop()

def export_data(layers: list[tuple[str, np.ndarray]], target_dir: str, mode: str) -> None:
    """ Routes data to disk based entirely on the selected mode.

    Args:
        layers: List of tuples containing band names and their corresponding 3D arrays.
        target_dir: Directory path where the output files will be saved.
        mode: Export mode, either "hypercube", "array", or "jpg".

    Returns:
        None. Side effect: Writes files to disk.
    """
    match mode:
        case "hypercube":
            arrays = [matrix for _, matrix in layers]
            band_names = [name for name, _ in layers]
            # Stack into a single 4D array: (Height, Width, Channels, Bands)
            hypercube = np.stack(arrays, axis=-1)
            output_file = os.path.join(target_dir, "multispectral_cube.npz")
            np.savez_compressed(output_file, data=hypercube, bands=band_names)
            print(f"\n[SUCCESS] Exported 4D Hypercube to {output_file} (Shape: {hypercube.shape})")
        case "array":
            print("\n[EXPORT] Writing discrete spectral layers (.npy arrays) to disk...")
            for band_name, frame_matrix in layers:
                output_file = os.path.join(target_dir, f"capture_{band_name}.npy")
                np.save(output_file, frame_matrix)
                print(f" Saved array: {output_file}")
        case "jpg":
            print("\n[EXPORT] Converting and encoding spectral layers to visual images (.jpg)...")
            for band_name, frame_matrix in layers:
                # Crucial check: Picamera2 captures in RGB, OpenCV writes files in BGR layout.
                bgr_matrix = cv2.cvtColor(frame_matrix, cv2.COLOR_RGB2BGR)
                output_file = os.path.join(target_dir, f"capture_{band_name}.jpg")
                cv2.imwrite(output_file, bgr_matrix)
                print(f" Saved image visual: {output_file}")
        case _:
            raise ValueError(f"Unknown export mode configuration variant: {mode}")
                
    

def main():
    ensure_directory(OUTPUT_DIR)
    
    if not Picamera2.global_camera_info():
        print("\n[ERROR] Camera hardware connection failure", file=sys.stderr)
        sys.exit(1)
        
    try:
        camera = Picamera2()
        config = camera.create_preview_configuration(buffer_count=2)
        camera.configure(config)
        camera.set_controls(DEFAULT_CAMERA_SETTINGS)
        camera.start()
        if is_standard_capture_enabled:
            layers = acquire_standard_photo(camera, config)
        else:
            layers = acquire_spectral_cube(camera, config)
        export_data(layers, OUTPUT_DIR, EXPORT_MODE)

    except Exception as e:
        print(f"\n[ERROR] Failed multispectral block acquisition: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()