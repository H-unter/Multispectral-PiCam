#!/usr/bin/python3
import os
from nicegui import app, ui
from camera_hardware import CameraHardware, SPECTRAL_CONFIG

# --- 1. CONFIGURATION ---
STAGING_DIR = os.path.abspath('./images')
os.makedirs(STAGING_DIR, exist_ok=True)

hardware_instances = {
    0: CameraHardware(),
    # 1: CameraHardware() # Uncomment when dual hardware logic is ready
}

is_capturing = False
viewers = {}

# --- 2. HARDWARE LIFECYCLE & CONTROLS ---
def setup_hardware():
    print("Booting hardware...")
    for hw in hardware_instances.values():
        hw.setup()
    ui.notify("Hardware ready! Live preview started.", type="positive")

def teardown_hardware():
    for hw in hardware_instances.values():
        hw.teardown()

app.on_shutdown(teardown_hardware)

def update_live_preview():
    if is_capturing:
        return
    for cam_id, hw in hardware_instances.items():
        if hw.is_ready:
            try:
                preview = hw.capture_preview_jpeg()
                if preview is not None and cam_id in viewers:
                    viewers[cam_id].set_source(f'data:image/jpeg;base64,{preview}')
            except Exception:
                pass 

def update_focus(cam_id, value):
    hw = hardware_instances.get(cam_id)
    if hw and hw.is_ready and not is_capturing:
        try:
            hw.set_focus(float(value))
        except Exception:
            pass

def execute_capture_and_download(cam_id, file_name):
    global is_capturing
    hw = hardware_instances.get(cam_id)
    
    if not hw or not hw.is_ready:
        ui.notify(f"Camera {cam_id} is not ready.", type="warning")
        return
        
    is_capturing = True 
    ui.notify(f"Capturing Camera {cam_id}...", type="info")
    
    try:
        hw.set_resolution(high_res=True)
        
        # 1. Acquire Data (Hardcoded to Standard Photo)
        layers = hw.acquire_standard_photo()
            
        # 2. Save temporarily on the Pi (Hardcoded to JPG)
        hw.export_data(layers, STAGING_DIR, "jpg")
        
        # 3. Locate the file based on camera_hardware.py logic 
        if layers:
            band_name = layers[0][0] 
            staged_file = os.path.join(STAGING_DIR, f"capture_{band_name}.jpg")
            download_name = f"{file_name}.jpg"
            
            # 4. Trigger the browser download with the custom name
            if staged_file and os.path.exists(staged_file):
                ui.download(staged_file, download_name)
                ui.notify(f"Download initiated for {download_name}!", type="positive")
        
    except Exception as e:
        ui.notify(f"Hardware failure on Cam {cam_id}: {e}", type="negative")
    finally:
        hw.set_resolution(high_res=False)
        is_capturing = False

# --- 3. FRONTEND LAYOUT ---
ui.label('Multispectral Camera Control').classes('text-2xl font-bold mb-4 w-full text-center')

with ui.tabs().classes('w-full') as tabs:
    general_tab = ui.tab('General Settings & Testing')
    led_tab = ui.tab('Per LED Config')

with ui.tab_panels(tabs, value=general_tab).classes('w-full bg-transparent'):
    
    # --- GENERAL TAB ---
    with ui.tab_panel(general_tab).classes('w-full p-0'):
        # Flex container to stretch cameras horizontally
        with ui.row().classes('w-full flex-nowrap gap-4 items-stretch'):
            
            for cam_id in [0, 1]: 
                # Cards will grow to fill available horizontal space equally
                with ui.card().classes('w-1/2 flex-grow flex flex-col justify-between'):
                    ui.label(f'CSI Port {cam_id}').classes('text-xl font-bold mb-2')
                    
                    # Live Preview
                    viewers[cam_id] = ui.interactive_image().classes('w-full rounded border bg-gray-100 min-h-[350px] flex-grow')
                    
                    ui.separator().classes('my-4 w-full')
                    
                    # Manual Focus 
                    with ui.row().classes('w-full items-center mb-2 gap-2'):
                        ui.label('Focus').classes('font-bold text-gray-700 whitespace-nowrap')
                        focus_slider = ui.slider(min=0.0, max=10.0, step=0.1, value=0.0, 
                                                 on_change=lambda e, c=cam_id: update_focus(c, e.value)).classes('flex-grow')
                        ui.label().bind_text_from(focus_slider, 'value', backward=lambda v: f'{v:.1f}').classes('font-mono w-8 text-right')
                    
                    ui.separator().classes('my-2 w-full')
                    
                    # Download Settings 
                    ui.label('Download Settings').classes('font-bold text-gray-700 mt-2')
                    with ui.row().classes('w-full gap-4 mt-2'):
                        file_name = ui.input('Output Filename', value=f'capture_cam{cam_id}').classes('flex-grow w-full')
                    
                    # Capture & Download Button
                    ui.button(
                        'Capture & Download (.jpg)', 
                        icon='download',
                        on_click=lambda c=cam_id, n=file_name: execute_capture_and_download(c, n.value)
                    ).classes('w-full mt-4 bg-blue-600 text-white font-bold')

    # --- PER LED CONFIG TAB ---
    with ui.tab_panel(led_tab).classes('w-full'):
        ui.label('LED Configuration Interface').classes('text-xl text-gray-500 italic')

ui.timer(0.5, setup_hardware, once=True)
ui.timer(0.2, update_live_preview)

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(port=8080, host='0.0.0.0', reload=False, favicon='📷')