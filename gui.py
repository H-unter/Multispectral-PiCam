#!/usr/bin/python3
import logging
import os
from nicegui import app, ui

from config import SPECTRAL_CHANNELS
from camera_hardware import CameraHardware 

logger = logging.getLogger(__name__)

STAGING_DIR = os.path.abspath('./images')
PORT = int(os.getenv('CAMERA_GUI_PORT', '8080'))
os.makedirs(STAGING_DIR, exist_ok=True)

hardware_instances = { # TODO: Extend this to support multiple cameras if needed, does i
    0: CameraHardware(),
}
is_capturing = False
viewers = {}
preview_failures = set()

# --- HARDWARE LIFECYCLE (Unchanged from previous) ---
def setup_hardware():
    for hw in hardware_instances.values(): hw.setup()
    ui.notify("Hardware ready! Live preview started.", type="positive")

def teardown_hardware():
    for hw in hardware_instances.values(): hw.teardown()

app.on_shutdown(teardown_hardware)

def update_live_preview():
    if not is_capturing:
        for cam_id, hw in hardware_instances.items():
            if hw.is_ready:
                try:
                    preview = hw.capture_preview_jpeg()
                    if preview is not None and cam_id in viewers:
                        viewers[cam_id].set_source(f'data:image/jpeg;base64,{preview}')
                    preview_failures.discard(cam_id)
                except Exception:
                    if cam_id not in preview_failures:
                        logger.exception("Live preview update failed for camera %s", cam_id)
                        preview_failures.add(cam_id)

def update_focus(cam_id, value):
    hw = hardware_instances.get(cam_id)
    if hw and hw.is_ready and not is_capturing:
        try:
            hw.set_focus(float(value))
        except Exception:
            logger.exception("Focus update failed for camera %s", cam_id)

def execute_capture_and_download(cam_id, file_name):
    global is_capturing
    hw = hardware_instances.get(cam_id)
    if not hw or not hw.is_ready: return
        
    is_capturing = True 
    ui.notify(f"Capturing Camera {cam_id}...", type="info")
    
    try:
        hw.set_resolution(high_res=True)
        layers = hw.acquire_standard_photo()
        hw.export_data(layers, STAGING_DIR, "jpg")
        
        if layers:
            band_name = layers[0][0] 
            staged_file = os.path.join(STAGING_DIR, f"capture_{band_name}.jpg")
            if os.path.exists(staged_file):
                ui.download(staged_file, f"{file_name}.jpg")
                ui.notify(f"Download initiated for {file_name}.jpg!", type="positive")
    except Exception as e:
        ui.notify(f"Hardware failure: {e}", type="negative")
    finally:
        try:
            if hw.is_ready:
                hw.set_resolution(high_res=False)
        except Exception:
            logger.exception("Could not restore preview resolution for camera %s", cam_id)
            ui.notify("Could not restore the live preview", type="negative")
        finally:
            is_capturing = False

# --- FRONTEND LAYOUT ---
ui.label('Multispectral Camera Control').classes('text-2xl font-bold mb-4 w-full text-center')

with ui.tabs().classes('w-full') as tabs:
    general_tab = ui.tab('General Settings & Testing')
    led_tab = ui.tab('Per LED Config')

with ui.tab_panels(tabs, value=general_tab).classes('w-full bg-transparent'):
    
    # --- GENERAL TAB (Unchanged) ---
    with ui.tab_panel(general_tab).classes('w-full p-0'):
        with ui.row().classes('w-full flex-nowrap gap-4 items-stretch'):
            for cam_id in hardware_instances:
                with ui.card().classes('w-1/2 flex-grow flex flex-col justify-between'):
                    ui.label(f'CSI Port {cam_id}').classes('text-xl font-bold mb-2')
                    viewers[cam_id] = ui.interactive_image().classes('w-full rounded border bg-gray-100 min-h-[350px] flex-grow')
                    ui.separator().classes('my-4 w-full')
                    
                    with ui.row().classes('w-full items-center mb-2 gap-2'):
                        ui.label('Focus').classes('font-bold text-gray-700 whitespace-nowrap')
                        focus_slider = ui.slider(min=0.0, max=10.0, step=0.1, value=0.0, 
                                                 on_change=lambda e, c=cam_id: update_focus(c, e.value)).classes('flex-grow')
                        ui.label().bind_text_from(focus_slider, 'value', backward=lambda v: f'{v:.1f}').classes('font-mono w-8 text-right')
                    
                    ui.separator().classes('my-2 w-full')
                    ui.label('Download Settings').classes('font-bold text-gray-700 mt-2')
                    file_name = ui.input('Output Filename', value=f'capture_cam{cam_id}').classes('w-full mt-2')
                    ui.button('Capture & Download (.jpg)', icon='download',
                              on_click=lambda c=cam_id, n=file_name: execute_capture_and_download(c, n.value)
                             ).classes('w-full mt-4 bg-blue-600 text-white font-bold')

    # --- PER LED CONFIG TAB ---
    with ui.tab_panel(led_tab).classes('w-full p-0'):
        with ui.row().classes('w-full gap-4 flex-wrap items-stretch'):            
            for channel in SPECTRAL_CHANNELS:
                with ui.card().classes('flex-grow min-w-[300px] w-1/3'):
                    ui.label(channel.name).classes('text-xl font-bold text-blue-600 mb-2')
                    if channel.led:
                        ui.label(f"Peak: {channel.led.peak_wavelength_nm}nm | Model: {channel.led.model_number}").classes('text-sm text-gray-500 mb-4')
                    else:
                        ui.label("Sensor Isolation (No LED)").classes('text-sm text-gray-500 mb-4')
                    ui.separator().classes('mb-4 w-full')
                    
                    # --- Camera Settings Binding ---
                    ui.label('Camera Settings').classes('font-bold text-gray-700 mb-2')
                    
                    # Note the use of bind_value! Changing this input instantly changes channel.camera.exposure_time_us
                    ui.number('Exposure Time (us)', format='%.0f').bind_value(channel.camera, 'exposure_time_us').classes('w-full mb-2')
                    ui.number('Analogue Gain', format='%.1f').bind_value(channel.camera, 'analogue_gain').classes('w-full mb-4')

                    # --- Driver Settings Binding ---
                    ui.label('Driver Settings').classes('font-bold text-gray-700 mb-2')
                    
                    if channel.driver.gpio_pin is not None:
                        ui.number('GPIO Pin', format='%.0f').bind_value(channel.driver, 'gpio_pin').classes('w-full mb-2')
                        
                        # Add a slider for drive current, capped by the LED's physical max limit
                        max_ma = channel.led.max_current_ma if channel.led else 1000
                        ui.label(f'Drive Current (Max: {max_ma}mA)').classes('text-sm')
                        with ui.row().classes('w-full items-center gap-2 mb-2'):
                            ui.slider(min=0, max=max_ma, step=10).bind_value(channel.driver, 'drive_current_ma').classes('flex-grow')
                            ui.label().bind_text_from(channel.driver, 'drive_current_ma', backward=lambda v: f'{v:.0f}mA').classes('font-mono w-12 text-right')
                    else:
                        ui.label('No driving circuitry required.').classes('italic text-gray-500')

ui.timer(0.5, setup_hardware, once=True)
ui.timer(0.2, update_live_preview)

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(port=PORT, host='0.0.0.0', reload=False, favicon='📷')