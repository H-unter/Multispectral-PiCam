#!/usr/bin/python3
import logging
import base64
import json
import os
import time
from uuid import uuid4
from typing import Any

import cv2
import numpy as np
from nicegui import app, run, ui

from config import CAMERA_CONFIG, SPECTRAL_CHANNELS
from hardware_runtime import hardware_instances, led_driver, shutdown
from models import MultispectralImage

logger = logging.getLogger(__name__)
if os.getenv('CAMERA_GUI_PROFILE'):
    logging.basicConfig(level=logging.INFO)


async def profile_http_requests(request, call_next):
    if not os.getenv('CAMERA_GUI_PROFILE'):
        return await call_next(request)
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info('HTTP %s %s -> %s in %.1f ms', request.method, request.url.path, response.status_code, elapsed_ms)
    return response


if os.getenv('CAMERA_GUI_PROFILE') and not getattr(app, '_camera_profile_middleware_registered', False):
    app.middleware('http')(profile_http_requests)
    setattr(app, '_camera_profile_middleware_registered', True)

STAGING_DIR = os.path.abspath('./images')
CUBE_PATH = os.path.join(STAGING_DIR, 'multispectral_cube.npz')
PORT = int(os.getenv('CAMERA_GUI_PORT', '8080'))
os.makedirs(STAGING_DIR, exist_ok=True)

camera_labels = {
    definition.camera_id: definition.label
    for definition in CAMERA_CONFIG
}
is_capturing = False
viewers = {}
preview_failures = set()
selected_channel_name = None
hardware_setup_attempted = False
hardware_setup_error = None
loaded_cube: MultispectralImage | None = None
cube_path_input: Any = None
band_select: Any = None
false_color_selects = []
band_image: Any = None
false_color_image: Any = None
band_viewer_frame: Any = None
false_color_viewer_frame: Any = None
histogram_chart: Any = None
metadata_display: Any = None
band_title: Any = None
false_color_positions = [0, 1, 2]
marker_sliders = []
focus_sliders = {}
channel_selector: Any = None
channel_cards = {}
channel_buttons = {}
capture_statuses = {}
SENSOR_WIDTH, SENSOR_HEIGHT = 4608, 2592
PREVIEW_WIDTH, PREVIEW_HEIGHT = 800, 450
preview_crop_centers = {
    cam_id: [PREVIEW_WIDTH / 2, PREVIEW_HEIGHT / 2]
    for cam_id in hardware_instances
}
preview_dragging = set()
preview_crop_overlays = {}
crop_size_inputs = {}

def _preview_event_position(event) -> tuple[float, float] | None:
    x = getattr(event, 'image_x', None)
    y = getattr(event, 'image_y', None)
    if x is None or y is None:
        return None
    return (
        max(0.0, min(PREVIEW_WIDTH, float(x))),
        max(0.0, min(PREVIEW_HEIGHT, float(y))),
    )


def _crop_preview_size(crop_size: int) -> float:
    return crop_size * PREVIEW_WIDTH / SENSOR_WIDTH


def _update_crop_overlay(cam_id: str) -> None:
    overlay = preview_crop_overlays.get(cam_id)
    if overlay is None:
        return
    crop_size = int(crop_size_inputs[cam_id].value or 700)
    crop_size = max(32, min(crop_size, SENSOR_HEIGHT, SENSOR_WIDTH))
    preview_size = _crop_preview_size(crop_size)
    center_x, center_y = preview_crop_centers[cam_id]
    left = max(0.0, min(PREVIEW_WIDTH - preview_size, center_x - preview_size / 2))
    top = max(0.0, min(PREVIEW_HEIGHT - preview_size, center_y - preview_size / 2))
    overlay.style(
        f'left: {left:.1f}px; top: {top:.1f}px; '
        f'width: {preview_size:.1f}px; height: {preview_size:.1f}px;'
    )


def _update_crop_center(cam_id: str, event) -> None:
    position = _preview_event_position(event)
    if position is None or is_capturing:
        return
    preview_crop_centers[cam_id][:] = position
    _update_crop_overlay(cam_id)


def _start_crop_drag(cam_id: str, event) -> None:
    if not is_capturing:
        preview_dragging.add(cam_id)
        _update_crop_center(cam_id, event)


def _drag_crop(cam_id: str, event) -> None:
    if cam_id in preview_dragging:
        _update_crop_center(cam_id, event)


def _stop_crop_drag(cam_id: str, _event) -> None:
    preview_dragging.discard(cam_id)


def _handle_preview_mouse(cam_id: str, event) -> None:
    event_name = getattr(event, 'type', '')
    if event_name == 'mousedown':
        _start_crop_drag(cam_id, event)
    elif event_name == 'mousemove':
        _drag_crop(cam_id, event)
    else:
        _stop_crop_drag(cam_id, event)


def _preview_crop_for_capture(cam_id: str) -> tuple[int, int, int, int]:
    crop_size = int(crop_size_inputs[cam_id].value or 700)
    crop_size = max(32, min(crop_size, SENSOR_HEIGHT, SENSOR_WIDTH))
    center_x, center_y = preview_crop_centers[cam_id]

    left = center_x * SENSOR_WIDTH / PREVIEW_WIDTH - crop_size / 2
    top = center_y * SENSOR_HEIGHT / PREVIEW_HEIGHT - crop_size / 2
    left = max(0, min(int(round(left)), SENSOR_WIDTH - crop_size))
    top = max(0, min(int(round(top)), SENSOR_HEIGHT - crop_size))
    return left, top, crop_size, crop_size


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

# --- HARDWARE LIFECYCLE ---
def initialize_hardware() -> None:
    global hardware_setup_attempted, hardware_setup_error
    if hardware_setup_attempted:
        return
    hardware_setup_attempted = True

    try:
        for hw in hardware_instances.values():
            hw.setup()
    except Exception as error:
        hardware_setup_error = error
        logger.exception("Hardware initialization failed")
        for hw in hardware_instances.values():
            hw.teardown()


def setup_hardware():
    initialize_hardware()
    if hardware_setup_error is not None:
        ui.notify(
            f"Camera unavailable. Stop other camera programs and restart the GUI: {hardware_setup_error}",
            type="negative",
            timeout=10000,
        )
        return

    for cam_id, hw in hardware_instances.items():
        focus_slider = focus_sliders[cam_id]
        focus_slider.enable()
        if selected_channel_name is not None:
            hw.set_active_channel(selected_channel_name)

    ui.notify("Hardware ready! Live preview started.", type="positive")

def teardown_hardware():
    shutdown()

app.on_shutdown(teardown_hardware)
initialize_hardware()

def update_live_preview():
    if not is_capturing:
        for cam_id, hw in hardware_instances.items():
            if hw.is_ready:
                try:
                    started = time.perf_counter()
                    preview = hw.capture_preview_jpeg()
                    if preview is not None and cam_id in viewers:
                        viewers[cam_id].set_source(f'data:image/jpeg;base64,{preview}')
                    if os.getenv('CAMERA_GUI_PROFILE'):
                        logger.info(
                            'Preview camera=%s bytes=%s in %.1f ms',
                            cam_id,
                            len(preview) if preview is not None else 0,
                            (time.perf_counter() - started) * 1000,
                        )
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

def update_channel_current(channel_name, value):
    if is_capturing:
        ui.notify("LED settings cannot change during a capture.", type="warning")
        return
    try:
        channel = SPECTRAL_CHANNELS[channel_name]
        current_ma = min(float(value), channel_max_current(channel))
        hardware = next(
            (hw for hw in hardware_instances.values() if hw.is_ready), None
        )
        if hardware is None:
            channel.driver.drive_current_ma = current_ma
        else:
            hardware.set_channel_current(channel_name, current_ma)
    except Exception as error:
        logger.exception("Could not update current for channel %s", channel_name)
        ui.notify(f"Could not update LED current: {error}", type="negative")


def channel_max_current(channel):
    led_limit = channel.led.max_current_ma if channel.led else led_driver.max_current_ma
    return min(float(led_limit), float(led_driver.max_current_ma))


def update_channel_card_styles():
    for name, card in channel_cards.items():
        if name == selected_channel_name:
            card.classes(add='bg-blue-100 ring-2 ring-blue-500')
        else:
            card.classes(remove='bg-blue-100 ring-2 ring-blue-500')
        if name in channel_buttons:
            channel_buttons[name].set_text('Off' if name == selected_channel_name else 'On')


def toggle_channel(channel_name):
    select_channel(None if selected_channel_name == channel_name else channel_name)


def select_channel(channel_name):
    global selected_channel_name
    if is_capturing:
        ui.notify("LED selection cannot change during a capture.", type="warning")
        return
    if channel_name == 'Off':
        channel_name = None
    selected_channel_name = channel_name
    if channel_selector is not None:
        channel_selector.value = channel_name
    update_channel_card_styles()

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

def _capture_standard_image(hw, staged_dir, scaler_crop):
    hw.set_resolution(high_res=True, scaler_crop=scaler_crop)
    try:
        layers = hw.acquire_standard_photo()
        hw.export_data(layers, staged_dir, "jpg")
        return layers
    finally:
        if hw.is_ready:
            hw.set_resolution(high_res=False)


def _capture_hypercube(hw, staged_file, scaler_crop):
    hw.set_resolution(high_res=True, scaler_crop=scaler_crop)
    try:
        image = hw.acquire_spectral_cube()
        image.export_npz(staged_file)
    finally:
        if hw.is_ready:
            hw.set_resolution(high_res=False)


async def execute_capture_and_download(cam_id, file_name):
    global is_capturing
    hw = hardware_instances.get(cam_id)
    if not hw or not hw.is_ready: return
    if is_capturing:
        ui.notify("Another capture is already in progress.", type="warning")
        return
        
    is_capturing = True 
    capture_statuses[cam_id].set_text('Capturing standard image...')
    ui.notify(f"Capturing Camera {cam_id}...", type="info")
    
    try:
        crop = _preview_crop_for_capture(cam_id)
        layers = await run.io_bound(_capture_standard_image, hw, STAGING_DIR, crop)
        
        if layers:
            band_name = layers[0][0] 
            staged_file = os.path.join(STAGING_DIR, f"capture_{band_name}.jpg")
            if os.path.exists(staged_file):
                ui.download(staged_file, f"{file_name}.jpg")
                capture_statuses[cam_id].set_text('Standard image ready for download.')
                ui.notify(f"Download initiated for {file_name}.jpg!", type="positive")
    except Exception as e:
        capture_statuses[cam_id].set_text('Standard image capture failed.')
        logger.exception("Standard capture failed for camera %s", cam_id)
        ui.notify(f"Hardware failure: {e}", type="negative")
    finally:
        is_capturing = False

async def execute_hypercube_capture_and_download(cam_id, file_name):
    global is_capturing
    hw = hardware_instances.get(cam_id)
    if not hw or not hw.is_ready:
        return
    if is_capturing:
        ui.notify("Another capture is already in progress.", type="warning")
        return

    is_capturing = True
    capture_statuses[cam_id].set_text(
        'Capturing multispectral cube with the current Per LED Config values...'
    )
    ui.notify(f'Capturing multispectral cube from Camera {cam_id}...', type='info')
    staged_file = os.path.join(
        STAGING_DIR,
        f'.multispectral_cube_{uuid4().hex}.npz',
    )

    try:
        crop = _preview_crop_for_capture(cam_id)
        await run.io_bound(_capture_hypercube, hw, staged_file, crop)
        if cube_path_input is not None:
            cube_path_input.value = staged_file
        ui.download(staged_file, f'{file_name}.npz')
        capture_statuses[cam_id].set_text('Multispectral cube ready for download.')
        ui.notify(f'Download initiated for {file_name}.npz!', type='positive')
    except Exception as error:
        logger.exception('Multispectral capture failed for camera %s', cam_id)
        capture_statuses[cam_id].set_text('Multispectral capture failed.')
        ui.notify(f'Hardware failure: {error}', type='negative')
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
        camera_count = len(hardware_instances)
        camera_row_alignment = ' justify-center' if camera_count == 1 else ''
        with ui.row().classes(f'w-full flex-wrap gap-4 items-stretch{camera_row_alignment}'):
            for cam_id in hardware_instances:
                hardware = hardware_instances[cam_id]
                camera_card_width = (
                    'w-full max-w-3xl'
                    if camera_count == 1
                    else 'w-full md:w-[calc(50%-0.5rem)] flex-grow'
                )
                with ui.card().classes(
                    f'{camera_card_width} min-w-0 flex flex-col justify-between'
                ):
                    ui.label(camera_labels[cam_id]).classes('text-xl font-bold mb-2')
                    with ui.element('div').classes(
                        'relative w-full aspect-video overflow-hidden rounded border bg-gray-100'
                    ):
                        viewers[cam_id] = ui.interactive_image(
                            on_mouse=lambda event, c=cam_id: _handle_preview_mouse(c, event),
                            events=['mousedown', 'mousemove', 'mouseup', 'mouseleave'],
                        ).classes('w-full h-full object-contain')
                        preview_crop_overlays[cam_id] = ui.element('div').classes(
                            'absolute pointer-events-none border-2 border-yellow-400 '
                            'bg-yellow-300/10'
                        )
                    ui.separator().classes('my-4 w-full')
                    
                    with ui.row().classes('w-full items-center mb-2 gap-2'):
                        ui.label('Focus').classes('font-bold text-gray-700 whitespace-nowrap')
                        focus_slider = ui.slider(
                            min=0.0,
                            max=hardware.focus_max,
                            step=0.1,
                            value=hardware.camera_settings.lens_position or 0.0,
                                                 on_change=lambda e, c=cam_id: update_focus(c, e.value)).classes('flex-grow')
                        focus_sliders[cam_id] = focus_slider
                        ui.label().bind_text_from(
                            focus_slider,
                            'value',
                            backward=lambda v: f'{v:.1f}' if v is not None else '-',
                        ).classes('font-mono w-8 text-right')
                    
                    ui.separator().classes('my-2 w-full')
                    ui.label('Capture').classes('font-bold text-gray-700 mt-2')
                    ui.label(
                        'Multispectral capture uses the exposure, gain, and LED-current '
                        'values configured in Per LED Config.'
                    ).classes('text-sm text-gray-500 mt-1')
                    crop_size_inputs[cam_id] = ui.number(
                        'Square crop size (sensor pixels)',
                        value=700,
                        min=32,
                        max=min(SENSOR_WIDTH, SENSOR_HEIGHT),
                        step=1,
                        on_change=lambda _event, c=cam_id: _update_crop_overlay(c),
                    ).classes('w-full mt-2')
                    ui.label(
                        'Drag the yellow square over the preview to choose an off-center sample.'
                    ).classes('text-sm text-gray-500 mt-1')
                    _update_crop_overlay(cam_id)
                    file_name = ui.input('Output Filename', value=f'capture_cam{cam_id}').classes('w-full mt-2')
                    ui.button('Capture & Download (.jpg)', icon='download',
                              on_click=lambda c=cam_id, n=file_name: execute_capture_and_download(c, n.value)
                             ).classes('w-full mt-4 bg-blue-600 text-white font-bold')
                    ui.button('Capture Hypercube (.npz)', icon='download',
                              on_click=lambda c=cam_id, n=file_name: execute_hypercube_capture_and_download(c, n.value)
                             ).classes('w-full mt-2 bg-purple-600 text-white font-bold')
                    capture_statuses[cam_id] = ui.label('Ready to capture.').classes(
                        'text-sm text-gray-500 mt-2'
                    )

    # --- PER LED CONFIG TAB ---
    with ui.tab_panel(led_tab).classes('w-full p-0'):
        ui.label('Manual LED Selection').classes('text-xl font-bold mb-2')
        channel_selector = ui.radio(
            {'Off': None, **{channel.name: channel.name for channel in SPECTRAL_CHANNELS}},
            value=None,
            on_change=lambda event: select_channel(
                None if event.value == 'Off' else event.value
            ),
        ).props('inline')
        ui.label('Select one channel at a time.').classes('text-sm text-gray-500 mb-4')

        with ui.row().classes('w-full grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 items-stretch'):
            for channel in SPECTRAL_CHANNELS:
                with ui.card().classes('min-w-0 p-3 flex flex-col') as channel_card:
                    channel_cards[channel.name] = channel_card
                    ui.label(channel.name).classes('text-lg font-bold text-blue-600 mb-1')
                    if channel.led:
                        ui.label(f"Peak: {channel.led.peak_wavelength_nm}nm | Model: {channel.led.model_number}").classes('text-xs text-gray-500 mb-2')
                    else:
                        ui.label("Sensor Isolation (No LED)").classes('text-xs text-gray-500 mb-2')
                    ui.separator().classes('mb-2 w-full')
                    
                    # --- Camera Settings Binding ---
                    ui.label('Camera Settings').classes('text-sm font-bold text-gray-700 mb-1')
                    
                    # Note the use of bind_value! Changing this input instantly changes channel.camera.exposure_time_us
                    ui.number('Exposure Time (us)', format='%.0f').bind_value(channel.camera, 'exposure_time_us').classes('w-full mb-1')
                    ui.number('Analogue Gain', format='%.1f').bind_value(channel.camera, 'analogue_gain').classes('w-full mb-2')

                    # --- Driver Settings Binding ---
                    ui.label('Driver Settings').classes('text-sm font-bold text-gray-700 mb-1')
                    
                    ui.label(
                        f'TLC5940 output channel {channel.driver.tlc5940_channel}'
                    ).classes('text-xs text-gray-500')
                    max_ma = channel_max_current(channel)
                    channel_current_ma = min(channel.driver.drive_current_ma, max_ma)
                    channel.driver.drive_current_ma = channel_current_ma
                    ui.label(f'Drive Current (Max: {max_ma:.1f}mA)').classes('text-xs')
                    with ui.row().classes('w-full items-center gap-1 mb-2'):
                        current_slider = ui.slider(
                            min=0,
                            max=max_ma,
                            step=0.1,
                            value=channel_current_ma,
                            on_change=lambda event, name=channel.name: update_channel_current(
                                name, event.value
                            ),
                        ).classes('flex-grow')
                        ui.label().bind_text_from(
                            current_slider,
                            'value',
                            backward=lambda value: f'{value:.1f}mA',
                        ).classes('font-mono w-12 text-right text-xs')
                    with ui.button(
                        'On',
                        icon='lightbulb',
                        on_click=lambda name=channel.name: toggle_channel(name),
                    ).props('dense').classes('w-full bg-blue-600 text-white') as channel_button:
                        channel_buttons[channel.name] = channel_button

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
                with ui.element('div').classes(
                    'w-full min-w-0 aspect-video bg-black border overflow-hidden'
                ) as band_viewer_frame:
                    band_image = ui.image().props('fit=contain').classes('w-full h-full')
            with ui.card().classes('min-w-0 p-3'):
                ui.label('False Color Composite').classes('text-lg font-bold')
                with ui.element('div').classes(
                    'w-full min-w-0 aspect-video bg-black border overflow-hidden'
                ) as false_color_viewer_frame:
                    false_color_image = ui.image().props('fit=contain').classes(
                        'w-full h-full'
                    )

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

ui.timer(0.5, setup_hardware, once=True)
ui.timer(float(os.getenv('CAMERA_PREVIEW_INTERVAL', '0.5')), update_live_preview)

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(port=PORT, host='0.0.0.0', reload=False, favicon='📷')