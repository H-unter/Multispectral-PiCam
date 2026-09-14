#!/usr/bin/python3
import os
import sys
import numpy as np
import cv2
import time
import base64
from picamera2 import Picamera2
from dataclasses import dataclass
from contextlib import contextmanager
from gpiozero import LED
from nicegui import app, ui

# --- 1. CONFIGURATION ---
OUTPUT_DIR = "./images"
EXPORT_MODE = "jpg"  

is_capturing = False
last_captured_file = None
camera = None
SPECTRAL_CHANNELS = {}

# Forced to Manual Focus by default so the slider has control
DEFAULT_CAMERA_SETTINGS = {
    "AeEnable": True,
    "AwbEnable": True,
    "AfMode": 0,            
    "LensPosition": 0.0     
}

SPECTRAL_CONFIG = {
    "led1": {"pin": 17,   "exposure": 1000000, "gain": 1.0},
    "led2": {"pin": 27,   "exposure": 1000000, "gain": 1.0},
    "led3": {"pin": 22,   "exposure": 1000000, "gain": 1.0},
    "dark": {"pin": None, "exposure": 1000000, "gain": 1.0}
}

@dataclass
class LedAttributes:
    led: LED | None
    exposure_time_us: int
    analogue_gain: float


# --- 2. HARDWARE LIFECYCLE ---
def set_camera_resolution(high_res: bool):
    """Bypasses memory limits by resizing the sensor dynamically."""
    global camera
    if camera is None:
        return
        
    camera.stop()
    if high_res:
        # Full 12MP for captures. Let PiCamera default to XBGR8888.
        config = camera.create_preview_configuration(main={"size": (4608, 2592)}, buffer_count=2)
    else:
        # Lightweight 800x600 for the UI live preview
        config = camera.create_preview_configuration(main={"size": (800, 600)}, buffer_count=2)
        
    camera.configure(config)
    
    # Ensure manual focus settings don't get wiped during the reset
    camera.set_controls(DEFAULT_CAMERA_SETTINGS)
    camera.start()

def setup_hardware():
    global camera, SPECTRAL_CHANNELS
    print("Booting hardware...")
    
    for band, cfg in SPECTRAL_CONFIG.items():
        SPECTRAL_CHANNELS[band] = LedAttributes(
            led=LED(cfg["pin"]) if cfg["pin"] is not None else None,
            exposure_time_us=cfg["exposure"],
            analogue_gain=cfg["gain"]
        )
        
    camera = Picamera2()
    # Initialize at low-res for the live preview
    set_camera_resolution(high_res=False)
    
    ui.notify("Hardware ready! Live preview started.", type="positive")
    print("Hardware ready! Live preview started.")

def teardown_hardware():
    global camera, SPECTRAL_CHANNELS
    if camera:
        camera.stop()
    for channel in SPECTRAL_CHANNELS.values():
        if channel.led:
            channel.led.close()

app.on_shutdown(teardown_hardware)


# --- 3. ACQUISITION FUNCTIONS ---
@contextmanager
def switch_lighting(channel: LedAttributes):
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

def acquire_standard_photo() -> list[tuple[str, np.ndarray]]:
    time.sleep(1.0) # Let the camera adjust to the lighting
    frame_array = camera.capture_array("main")
    return [("standard", frame_array)]

def acquire_spectral_cube() -> list[tuple[str, np.ndarray]]:
    captured_layers = []
    camera.set_controls({
        "AeEnable": False, 
        "AwbEnable": False,
        "ColourGains": (1.0, 1.0)
    })
    
    for band, channel in SPECTRAL_CHANNELS.items():
        with switch_lighting(channel):  
            camera.set_controls({
                "ExposureTime": channel.exposure_time_us,
                "AnalogueGain": channel.analogue_gain
            })
            time.sleep(0.2)
            frame_array = camera.capture_array("main")
            captured_layers.append((band, frame_array))
    return captured_layers

def export_data(layers: list[tuple[str, np.ndarray]], target_dir: str, mode: str) -> None:
    if mode == "jpg":
        for band_name, frame_matrix in layers:
            bgr_matrix = cv2.cvtColor(frame_matrix, cv2.COLOR_RGB2BGR)
            output_file = os.path.join(target_dir, f"capture_{band_name}.jpg")
            cv2.imwrite(output_file, bgr_matrix)


# --- 4. NICEGUI WEB INTERFACE ---
ensure_directory(OUTPUT_DIR)
app.add_static_files('/local_images', OUTPUT_DIR)

def update_live_preview():
    if camera is None or is_capturing:
        return
    try:
        frame = camera.capture_array("main")
        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        _, buffer = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, 40])
        b64_str = base64.b64encode(buffer).decode('utf-8')
        live_viewer.set_source(f'data:image/jpeg;base64,{b64_str}')
    except Exception:
        pass 

def update_focus(e):
    if camera is not None and not is_capturing:
        val = float(e.value)
        try:
            camera.set_controls({
                "AfMode": 0,
                "LensPosition": val
            })
            DEFAULT_CAMERA_SETTINGS["LensPosition"] = val
        except Exception:
            pass 

def trigger_capture():
    global is_capturing, last_captured_file
    if camera is None:
        ui.notify("Hardware is still booting...", type="warning")
        return
        
    is_capturing = True 
    ui.notify("Reconfiguring sensor for 12MP capture...", type="info")
    
    SPECTRAL_CHANNELS["led1"].exposure_time_us = int(led1_exposure.value)
    SPECTRAL_CHANNELS["led2"].exposure_time_us = int(led2_exposure.value)
    SPECTRAL_CHANNELS["led3"].exposure_time_us = int(led3_exposure.value)
    
    try:
        # Dynamically switch to 12 Megapixels
        set_camera_resolution(high_res=True)
        
        if is_standard.value:
            layers = acquire_standard_photo()
            export_data(layers, OUTPUT_DIR, "jpg")
            last_captured_file = os.path.join(OUTPUT_DIR, "capture_standard.jpg")
            latest_viewer.set_source(f'/local_images/capture_standard.jpg?t={time.time()}')
        else:
            layers = acquire_spectral_cube()
            export_data(layers, OUTPUT_DIR, "jpg")
            last_captured_file = os.path.join(OUTPUT_DIR, "capture_led1.jpg")
            latest_viewer.set_source(f'/local_images/capture_led1.jpg?t={time.time()}')
            
        ui.notify("Export complete!", type="positive")
        
    except Exception as e:
        ui.notify(f"Hardware failure: {e}", type="negative")
    finally:
        # Drop back to 800x600
        set_camera_resolution(high_res=False)
        is_capturing = False

def download_latest():
    if last_captured_file and os.path.exists(last_captured_file):
        ui.download(last_captured_file, os.path.basename(last_captured_file))
        ui.notify("Download started...", type="positive")
    else:
        ui.notify("No image has been captured yet!", type="warning")


# --- 5. FRONTEND LAYOUT ---
ui.label('Multispectral Camera Control').classes('text-2xl font-bold mb-4')

with ui.row().classes('gap-8'):
    with ui.column():
        with ui.card():
            ui.label('Hardware Settings').classes('font-bold text-lg mb-2')
            is_standard = ui.switch('Standard Capture Mode (RGB)', value=True)
            
            ui.separator().classes('my-2')
            
            ui.label('Manual Focus (Diopters)').classes('text-sm text-gray-500')
            with ui.row().classes('w-full items-center mb-2'):
                focus_slider = ui.slider(min=0.0, max=10.0, step=0.1, value=0.0, on_change=update_focus).classes('w-3/4')
                ui.label().bind_text_from(focus_slider, 'value', backward=lambda v: f'{v:.1f}').classes('ml-4 font-mono')
            
            ui.separator().classes('my-2')
            
            ui.label('Multispectral Exposures (us)').classes('text-sm text-gray-500')
            led1_exposure = ui.number('LED 1 (Pin 17)', value=SPECTRAL_CONFIG["led1"]["exposure"], format='%.0f')
            led2_exposure = ui.number('LED 2 (Pin 27)', value=SPECTRAL_CONFIG["led2"]["exposure"], format='%.0f')
            led3_exposure = ui.number('LED 3 (Pin 22)', value=SPECTRAL_CONFIG["led3"]["exposure"], format='%.0f')
            
            ui.button('Trigger Capture', on_click=trigger_capture).classes('mt-4 bg-blue-500 text-white w-full')

    with ui.column():
        with ui.card():
            ui.label('Live Preview').classes('font-bold text-lg mb-2')
            live_viewer = ui.interactive_image().classes('w-[500px] rounded border bg-gray-100 min-h-[375px]')
            
        with ui.card():
            ui.label('Latest High-Res Output').classes('font-bold text-lg mb-2')
            latest_viewer = ui.image().classes('w-[500px] rounded border bg-gray-100 min-h-[375px]')
            ui.button('Download Image', icon='download', on_click=download_latest).classes('w-full mt-2 bg-green-600 text-white')

ui.timer(0.5, setup_hardware, once=True)
ui.timer(0.2, update_live_preview)

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(port=8080, host='0.0.0.0', reload=False, favicon='📷')