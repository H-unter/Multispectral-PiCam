#!/usr/bin/python3
import logging
import base64
import json
import os
from typing import Any

import cv2
import numpy as np
from nicegui import app, ui

from config import SPECTRAL_CHANNELS
from camera_hardware import CameraHardware 
from models import MultispectralImage

logger = logging.getLogger(__name__)

STAGING_DIR = os.path.abspath('./images')
CUBE_PATH = os.path.join(STAGING_DIR, 'multispectral_cube.npz')
PORT = int(os.getenv('CAMERA_GUI_PORT', '8080'))
os.makedirs(STAGING_DIR, exist_ok=True)

hardware_instances = { # TODO: Extend this to support multiple cameras if needed, does i
    0: CameraHardware(),
}
is_capturing = False
viewers = {}
preview_failures = set()
selected_channel_name = None
hardware_setup_attempted = False
loaded_cube: MultispectralImage | None = None
cube_path_input: Any = None
band_select: Any = None
false_color_selects = []
band_image: Any = None
false_color_image: Any = None
histogram_chart: Any = None
metadata_display: Any = None
band_title: Any = None
false_color_positions = [0, 1, 2]
marker_sliders = []


def _image_data_uri(image: np.ndarray, color: bool = False) -> str:
    image = np.asarray(image)
    if image.dtype != np.uint8:
        image = np.clip(image, 0, 255).astype(np.uint8)
    if color:
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    success, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not success:
        raise ValueError('Could not encode viewer image')
    return f"data:image/jpeg;base64,{base64.b64encode(encoded).decode('ascii')}"


def _normalize_band(band: np.ndarray) -> np.ndarray:
    band = np.asarray(band, dtype=np.float32)
    low, high = np.percentile(band, [1, 99])
    if high <= low:
        return np.zeros(band.shape, dtype=np.uint8)
    return np.clip((band - low) * 255.0 / (high - low), 0, 255).astype(np.uint8)


def _update_chart(chart, options: dict) -> None:
    chart.options.clear()
    chart.options.update(options)
    chart.update()


def _update_viewer() -> None:
    if loaded_cube is None:
        return

    selected_name = band_select.value or loaded_cube.channel_names[0]
    band = loaded_cube.channel(selected_name)
    channel_metadata = next(
        (
            channel for channel in loaded_cube.metadata.get('channels', [])
            if channel.get('name') == selected_name
        ),
        {},
    )
    led_metadata = channel_metadata.get('configuration', {}).get('led') or {}
    wavelength = led_metadata.get('peak_wavelength_nm')
    wavelength_text = f' | {wavelength:g} nm' if wavelength is not None else ''
    band_title.set_text(f'Band Viewer | {selected_name}{wavelength_text}')
    band_image.set_source(_image_data_uri(_normalize_band(band)))

    selected_indices = [
        loaded_cube.channel_names[position]
        for position in false_color_positions
    ]
    composite = np.stack(
        [_normalize_band(loaded_cube.channel(index)) for index in selected_indices],
        axis=-1,
    )
    false_color_image.set_source(_image_data_uri(composite, color=True))

    means = [float(np.mean(loaded_cube.channel(name))) for name in loaded_cube.channel_names]
    _update_chart(histogram_chart, {
        'xAxis': {
            'type': 'category',
            'data': loaded_cube.channel_names,
            'axisLabel': {'interval': 0, 'rotate': 25},
        },
        'yAxis': {'type': 'value'},
        'series': [{
            'type': 'bar',
            'data': means,
            'itemStyle': {'color': '#64748b'},
            'emphasis': {'itemStyle': {'color': '#2563eb'}},
            'markLine': {
                'symbol': ['none', 'none'],
                'silent': True,
                'label': {'show': True},
                'data': [
                    {
                        'xAxis': loaded_cube.channel_names[position],
                        'name': label,
                        'lineStyle': {'color': color, 'width': 3},
                    }
                    for position, (label, color) in zip(
                        false_color_positions,
                        (('R', '#dc2626'), ('G', '#16a34a'), ('B', '#2563eb')),
                    )
                ],
            },
        }],
        'grid': {'left': 55, 'right': 25, 'top': 35, 'bottom': 75},
        'tooltip': {'trigger': 'axis'},
    })


def select_histogram_band(event) -> None:
    if loaded_cube is None:
        return
    position = int(event.data_index)
    if 0 <= position < len(loaded_cube.channel_names):
        band_select.value = loaded_cube.channel_names[position]
        _update_viewer()


def move_false_color_marker(index: int, event) -> None:
    if loaded_cube is None:
        return
    false_color_positions[index] = max(
        0, min(int(event.value), len(loaded_cube.channel_names) - 1)
    )
    _update_viewer()


def load_cube() -> None:
    global loaded_cube
    try:
        cube_path = cube_path_input.value or CUBE_PATH
        loaded_cube = MultispectralImage.import_npz(cube_path)
        options = {name: name for name in loaded_cube.channel_names}
        band_select.options = options
        band_select.value = loaded_cube.channel_names[0]
        false_color_positions[:] = [
            min(index, len(loaded_cube.channel_names) - 1)
            for index in range(3)
        ]
        for index, slider in enumerate(marker_sliders):
            slider.max = len(loaded_cube.channel_names) - 1
            slider.value = false_color_positions[index]
        metadata_display.set_text(json.dumps(loaded_cube.metadata, indent=2))
        _update_viewer()
        ui.notify(f'Loaded {len(loaded_cube.channel_names)} spectral channels', type='positive')
    except Exception as error:
        loaded_cube = None
        logger.exception('Could not load multispectral cube')
        ui.notify(f'Could not load cube: {error}', type='negative')

# --- HARDWARE LIFECYCLE (Unchanged from previous) ---
def setup_hardware():
    global hardware_setup_attempted
    if hardware_setup_attempted:
        return
    hardware_setup_attempted = True

    try:
        for hw in hardware_instances.values():
            hw.setup()
            if selected_channel_name is not None:
                hw.set_active_channel(selected_channel_name)
    except Exception as error:
        logger.exception("Hardware initialization failed")
        for hw in hardware_instances.values():
            hw.teardown()
        ui.notify(
            f"Camera unavailable. Stop other camera programs and restart the GUI: {error}",
            type="negative",
            timeout=10000,
        )
        return

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

def select_channel(channel_name):
    global selected_channel_name
    selected_channel_name = channel_name

    try:
        ready_hardware = [hw for hw in hardware_instances.values() if hw.is_ready]
        if not ready_hardware:
            return
        for hw in ready_hardware:
            hw.set_active_channel(channel_name)
        ui.notify(
            f"Active channel: {channel_name or 'all LEDs off'}",
            type="positive",
        )
    except Exception as error:
        logger.exception("Could not select spectral channel %s", channel_name)
        ui.notify(f"Could not select channel: {error}", type="negative")

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
    viewer_tab = ui.tab('Cube Viewer')

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
        ui.label('Manual LED Selection').classes('text-xl font-bold mb-2')
        ui.radio(
            {channel.name: channel.name for channel in SPECTRAL_CHANNELS},
            value=None,
            on_change=lambda event: select_channel(event.value),
        ).props('inline')
        ui.label('Select one channel at a time.').classes('text-sm text-gray-500 mb-4')

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

    # --- MULTISPECTRAL CUBE VIEWER ---
    with ui.tab_panel(viewer_tab).classes('w-full p-0'):
        ui.label('Multispectral Cube Viewer').classes('text-2xl font-bold mb-3')
        with ui.row().classes('w-full grid grid-cols-1 md:grid-cols-2 gap-3 items-stretch'):
            with ui.card().classes('min-w-0 p-3'):
                with ui.row().classes('w-full items-end gap-3'):
                    cube_path_input = ui.input('NPZ cube path', value=CUBE_PATH).classes('flex-grow')
                    ui.button('Load Cube', icon='folder_open', on_click=load_cube).classes('bg-blue-600 text-white')
            with ui.card().classes('min-w-0 p-3'):
                ui.label('Metadata').classes('text-lg font-bold')
                metadata_display = ui.label('No cube loaded').classes(
                    'w-full max-h-32 overflow-auto whitespace-pre-wrap break-words '
                    'pl-3 pr-2 py-2 bg-gray-50 border rounded font-mono text-xs'
                )

        with ui.row().classes('w-full grid grid-cols-1 md:grid-cols-2 gap-3 items-stretch mt-3'):
            with ui.card().classes('min-w-0 p-3'):
                band_title = ui.label('Band Viewer').classes('text-lg font-bold')
                with ui.element('div').classes('w-full h-[300px] bg-gray-100 border flex items-center justify-center overflow-hidden'):
                    band_image = ui.image().classes('max-w-full max-h-full object-contain')
            with ui.card().classes('min-w-0 p-3'):
                ui.label('False Color Composite').classes('text-lg font-bold')
                with ui.element('div').classes('w-full h-[300px] bg-gray-100 border flex items-center justify-center overflow-hidden'):
                    false_color_image = ui.image().classes('max-w-full max-h-full object-contain')

        with ui.card().classes('w-full mt-3 p-3'):
            ui.label('Channel Histogram and False-Color Controls').classes('text-lg font-bold')
            ui.label('Click a bar to view that band. Move the colored markers to assign red, green, and blue channels.').classes('text-sm text-gray-500')
            band_select = ui.select({}, label='Selected band', on_change=lambda _: _update_viewer()).classes('w-64 mt-2')
            histogram_chart = ui.echart({}, on_point_click=select_histogram_band).classes('w-full h-64')
            with ui.row().classes('w-full items-center gap-4 mt-2'):
                for index, (label, color) in enumerate((('Red', 'red'), ('Green', 'green'), ('Blue', 'blue'))):
                    with ui.row().classes('flex-grow items-center gap-2'):
                        ui.label(label).classes(f'text-{color}-600 font-bold w-12')
                        marker_sliders.append(
                            ui.slider(
                                min=0,
                                max=2,
                                step=1,
                                value=index,
                                on_change=lambda event, i=index: move_false_color_marker(i, event),
                            ).classes('flex-grow')
                        )

        if os.path.exists(CUBE_PATH):
            load_cube()

ui.timer(0.5, setup_hardware, once=True)
ui.timer(0.2, update_live_preview)

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(port=PORT, host='0.0.0.0', reload=False, favicon='📷')