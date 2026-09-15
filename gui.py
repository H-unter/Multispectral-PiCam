#!/usr/bin/python3
import os
import time
from nicegui import app, ui
from camera_hardware import CameraHardware, SPECTRAL_CONFIG

# --- 1. CONFIGURATION ---
OUTPUT_DIR = "./images"
EXPORT_MODE = "jpg"  

is_capturing = False
last_captured_file = None
hardware = CameraHardware()


# --- 4. NICEGUI WEB INTERFACE ---
os.makedirs(OUTPUT_DIR, exist_ok=True)
app.add_static_files('/local_images', OUTPUT_DIR)

def setup_hardware():
    print("Booting hardware...")
    hardware.setup()
    ui.notify("Hardware ready! Live preview started.", type="positive")
    print("Hardware ready! Live preview started.")

def teardown_hardware():
    hardware.teardown()

app.on_shutdown(teardown_hardware)

def update_live_preview():
    if not hardware.is_ready or is_capturing:
        return
    try:
        preview = hardware.capture_preview_jpeg()
        if preview is not None:
            live_viewer.set_source(f'data:image/jpeg;base64,{preview}')
    except Exception:
        pass 

def update_focus(e):
    if hardware.is_ready and not is_capturing:
        val = float(e.value)
        try:
            hardware.set_focus(val)
        except Exception:
            pass 

def trigger_capture():
    global is_capturing, last_captured_file
    if not hardware.is_ready:
        ui.notify("Hardware is still booting...", type="warning")
        return
        
    is_capturing = True 
    ui.notify("Reconfiguring sensor for 12MP capture...", type="info")
    
    hardware.set_exposures({
        "led1": int(led1_exposure.value if led1_exposure.value is not None else SPECTRAL_CONFIG["led1"]["exposure"]),
        "led2": int(led2_exposure.value if led2_exposure.value is not None else SPECTRAL_CONFIG["led2"]["exposure"]),
        "led3": int(led3_exposure.value if led3_exposure.value is not None else SPECTRAL_CONFIG["led3"]["exposure"]),
    })
    
    try:
        # Dynamically switch to 12 Megapixels
        hardware.set_resolution(high_res=True)
        
        if is_standard.value:
            layers = hardware.acquire_standard_photo()
            hardware.export_data(layers, OUTPUT_DIR, "jpg")
            last_captured_file = os.path.join(OUTPUT_DIR, "capture_standard.jpg")
            latest_viewer.set_source(f'/local_images/capture_standard.jpg?t={time.time()}')
        else:
            layers = hardware.acquire_spectral_cube()
            hardware.export_data(layers, OUTPUT_DIR, "jpg")
            last_captured_file = os.path.join(OUTPUT_DIR, "capture_led1.jpg")
            latest_viewer.set_source(f'/local_images/capture_led1.jpg?t={time.time()}')
            
        ui.notify("Export complete!", type="positive")
        
    except Exception as e:
        ui.notify(f"Hardware failure: {e}", type="negative")
    finally:
        # Drop back to 800x600
        hardware.set_resolution(high_res=False)
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