#!/usr/bin/python3
"""Low-level camera, lighting, acquisition, and export operations."""

import base64
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass

import cv2
import numpy as np
from gpiozero import LED
from picamera2 import Picamera2

from config import CHANNELS, DEFAULT_CAMERA_SETTINGS
from models import CameraSettings, SpectralChannel

logger = logging.getLogger(__name__)
_SHARED_LEDS = {}

@dataclass
class RuntimeChannel:
    config: SpectralChannel
    led: LED | None

class CameraHardware:
    def __init__(self) -> None:
        self.camera: Picamera2 | None = None
        self.runtime_channels: dict[str, RuntimeChannel] = {}

    @property
    def is_ready(self) -> bool:
        return self.camera is not None

    def setup(self) -> None:
        try:
            for channel_config in CHANNELS:
                pin = channel_config.driver.gpio_pin
                if pin is not None:
                    if pin not in _SHARED_LEDS:
                        _SHARED_LEDS[pin] = LED(pin)
                    led_instance = _SHARED_LEDS[pin]
                else:
                    led_instance = None

                self.runtime_channels[channel_config.name] = RuntimeChannel(
                    config=channel_config,
                    led=led_instance,
                )

            self.camera = Picamera2()
            self.set_resolution(high_res=False)
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
        config = self.camera.create_preview_configuration(
            main={"size": size}, buffer_count=2
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

    def capture_preview_jpeg(self, quality: int = 40) -> str | None:
        if self.camera is None:
            return None
        frame = self.camera.capture_array("main")
        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        _, buffer = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return base64.b64encode(buffer).decode("utf-8")

    def acquire_standard_photo(self) -> list[tuple[str, np.ndarray]]:
        if self.camera is None:
            raise RuntimeError("Camera is not ready")
            
        # Temporarily enable AE and AWB for standard photo
        standard_settings = CameraSettings(ae_enable=True, awb_enable=True)
        self.camera.set_controls(standard_settings.to_control_dict())
        time.sleep(1.0)
        
        return [("standard", self.camera.capture_array("main"))]

    def acquire_spectral_cube(self) -> list[tuple[str, np.ndarray]]:
        if self.camera is None:
            raise RuntimeError("Camera is not ready")

        captured_layers = []
        
        for band_name, rt_channel in self.runtime_channels.items():
            with self.switch_lighting(rt_channel):
                # Pass the channel's specific CameraSettings dataclass directly
                self.camera.set_controls(rt_channel.config.camera.to_control_dict())
                time.sleep(0.2)
                captured_layers.append((band_name, self.camera.capture_array("main")))
                
        return captured_layers

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
    def export_data(layers: list[tuple[str, np.ndarray]], target_dir: str, mode: str) -> None:
        # (Export logic remains unchanged)
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
                bgr_matrix = cv2.cvtColor(frame_matrix, cv2.COLOR_RGB2BGR)
                output_file = os.path.join(target_dir, f"capture_{band_name}.jpg")
                cv2.imwrite(output_file, bgr_matrix)
        else:
            raise ValueError(f"Unknown export mode configuration variant: {mode}")