#!/usr/bin/python3
"""Low-level camera, lighting, acquisition, and export operations."""

import base64
import logging
import os
import time
from contextlib import contextmanager
from typing import Callable

import cv2
import numpy as np
from gpiozero import LED
from picamera2 import Picamera2

from config import SPECTRAL_CHANNELS, DEFAULT_CAMERA_SETTINGS
from models import CameraSettings, MultispectralImage, SpectralChannel

logger = logging.getLogger(__name__)
_SHARED_LEDS = {}

class RuntimeChannel:
    """Bind a spectral-channel configuration to its GPIOZero LED hardware."""

    def __init__(self, config: SpectralChannel) -> None:
        self.config = config
        pin = config.driver.gpio_pin

        if pin is not None:
            if pin not in _SHARED_LEDS:
                _SHARED_LEDS[pin] = LED(pin)
            self.led = _SHARED_LEDS[pin]
        else:
            self.led = None

class CameraHardware:
    """Encapsulates the camera and lighting hardware, providing methods for setup, capture, and export."""
    def __init__(self) -> None:
        self.camera: Picamera2 | None = None
        self.runtime_channels: dict[str, RuntimeChannel] = {}
        self.camera_resolution: tuple[int, int] | None = None

    @property
    def is_ready(self) -> bool:
        return self.camera is not None

    def setup(self) -> None:
        try:
            for channel_config in SPECTRAL_CHANNELS:
                runtime_channel = RuntimeChannel(channel_config)
                self.runtime_channels[channel_config.name] = runtime_channel

            self.camera = Picamera2()
            self.set_resolution(high_res=True)
        except Exception:
            logger.exception("Camera hardware setup failed")
            self.teardown()
            raise

    def teardown(self) -> None:
        if self.camera is not None:
            try:
                self.camera.stop()
            except Exception:
                logger.exception("Camera shutdown failed")
            self.camera = None
            
        for channel in self.runtime_channels.values():
            if channel.led is not None:
                pin = channel.config.driver.gpio_pin
                if pin in _SHARED_LEDS and _SHARED_LEDS[pin] is channel.led:
                    try:
                        channel.led.close()
                    except Exception:
                        logger.exception("LED shutdown failed for GPIO %s", pin)
                    del _SHARED_LEDS[pin]
                    
        self.runtime_channels.clear()

    def set_resolution(self, high_res: bool) -> None:
        if self.camera is None:
            return

        self.camera.stop()
        size = (4608, 2592) if high_res else (800, 600)
        self.camera_resolution = size
        config = self.camera.create_preview_configuration(
            main={"size": size, "format": "RGB888"}, buffer_count=2
        )
        self.camera.configure(config)
        
        # Apply the default settings dataclass here
        self.camera.set_controls(DEFAULT_CAMERA_SETTINGS.to_control_dict())
        self.camera.start()

    def set_focus(self, value: float) -> None:
        if self.camera is None:
            return
            
        # Update the dataclass in memory so it persists
        DEFAULT_CAMERA_SETTINGS.lens_position = value
        
        # Apply the updated setting
        self.camera.set_controls(DEFAULT_CAMERA_SETTINGS.to_control_dict())

    def set_active_channel(self, channel_name: str | None) -> None:
        """Enable one configured channel LED and switch all other LEDs off."""
        if channel_name is not None and channel_name not in self.runtime_channels:
            raise ValueError(f"Unknown spectral channel: {channel_name}")

        for name, channel in self.runtime_channels.items():
            if channel.led is None:
                continue
            if name == channel_name:
                channel.led.on()
            else:
                channel.led.off()

    def capture_preview_jpeg(self, quality: int = 40) -> str | None:
        if self.camera is None:
            return None
        frame = self.camera.capture_array("main")
        _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return base64.b64encode(buffer).decode("utf-8")

    @staticmethod
    def average_rgb_channels(frame: np.ndarray) -> np.ndarray:
        """Reduce an RGB or XBGR8888 frame to one channel by averaging colors."""
        if frame.ndim != 3 or frame.shape[-1] not in (3, 4):
            raise ValueError(
                f"Expected an RGB or four-channel frame, received shape {frame.shape}"
            )
        return frame[..., -3:].mean(axis=-1)

    def acquire_standard_photo(
        self,
        process_frame: Callable[[np.ndarray], np.ndarray] | None = None,
    ) -> list[tuple[str, np.ndarray]]:
        if self.camera is None:
            raise RuntimeError("Camera is not ready")
            
        # Temporarily enable AE and AWB for standard photo
        standard_settings = CameraSettings(ae_enable=True, awb_enable=True)
        self.camera.set_controls(standard_settings.to_control_dict())
        time.sleep(1.0)
        
        frame = self.camera.capture_array("main")
        return [("standard", process_frame(frame) if process_frame else frame)]

    def acquire_spectral_cube(
        self,
        process_frame: Callable[[np.ndarray], np.ndarray] | None = None,
    ) -> MultispectralImage:
        if self.camera is None:
            raise RuntimeError("Camera is not ready")

        captured_layers = []
        processor = process_frame or self.average_rgb_channels
        
        for band_name, rt_channel in self.runtime_channels.items():
            with self.switch_lighting(rt_channel):
                # Pass the channel's specific CameraSettings dataclass directly
                self.camera.set_controls(rt_channel.config.camera.to_control_dict())
                time.sleep(0.2)
                frame = self.camera.capture_array("main")
                captured_layers.append((band_name, processor(frame)))
                
        image_height, image_width = captured_layers[0][1].shape
        resolution = self.camera_resolution or (image_width, image_height)
        return MultispectralImage.from_layers(
            captured_layers,
            channels=[channel.config for channel in self.runtime_channels.values()],
            metadata={"camera": {"resolution": list(resolution)}},
        )

    @staticmethod
    @contextmanager
    def switch_lighting(rt_channel: RuntimeChannel):
        if rt_channel.led is not None:
            rt_channel.led.on()
        else:
            print(f" Isolating sensor environment ({rt_channel.config.name})...")
            
        try:
            yield
        finally:
            if rt_channel.led is not None:
                rt_channel.led.off()

    @staticmethod
    def export_data(
        layers: MultispectralImage | list[tuple[str, np.ndarray]],
        target_dir: str,
        mode: str,
    ) -> None:
        if isinstance(layers, MultispectralImage):
            if mode in {"hypercube", "npz"}:
                layers.export_npz(os.path.join(target_dir, "multispectral_cube.npz"))
            elif mode == "jpg":
                layers.export_jpgs(target_dir)
            else:
                raise ValueError(f"Unknown export mode configuration variant: {mode}")
            return

        # Compatibility path for standard-photo callers.
        os.makedirs(target_dir, exist_ok=True)
        if mode == "hypercube":
            arrays = [matrix for _, matrix in layers]
            band_names = [name for name, _ in layers]
            np.savez_compressed(
                os.path.join(target_dir, "multispectral_cube.npz"),
                data=np.stack(arrays, axis=-1),
                bands=band_names,
            )
        elif mode == "array":
            for band_name, frame_matrix in layers:
                np.save(os.path.join(target_dir, f"capture_{band_name}.npy"), frame_matrix)
        elif mode == "jpg":
            for band_name, frame_matrix in layers:
                output_file = os.path.join(target_dir, f"capture_{band_name}.jpg")
                if frame_matrix.ndim == 3 and frame_matrix.shape[-1] == 4:
                    # Picamera2's four-channel frame has one leading padding byte.
                    frame_matrix = frame_matrix[..., 1:]
                cv2.imwrite(output_file, frame_matrix)
        else:
            raise ValueError(f"Unknown export mode configuration variant: {mode}")