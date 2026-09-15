#!/usr/bin/python3
"""Low-level camera, lighting, acquisition, and export operations."""

import base64
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass

import cv2
import numpy as np
from gpiozero import LED
from picamera2 import Picamera2


DEFAULT_CAMERA_SETTINGS = {
    "AeEnable": True,
    "AwbEnable": True,
    "AfMode": 0,
    "LensPosition": 10.0,
}

SPECTRAL_CONFIG = {
    "led1": {"pin": 17, "exposure": 1000000, "gain": 1.0},
    "led2": {"pin": 27, "exposure": 1000000, "gain": 1.0},
    "led3": {"pin": 22, "exposure": 1000000, "gain": 1.0},
    "dark": {"pin": None, "exposure": 1000000, "gain": 1.0},
}


@dataclass
class LedAttributes:
    led: LED | None
    exposure_time_us: int
    analogue_gain: float


class CameraHardware:
    """Owns the camera and lighting hardware used by the application."""

    def __init__(self) -> None:
        self.camera: Picamera2 | None = None
        self.spectral_channels: dict[str, LedAttributes] = {}

    @property
    def is_ready(self) -> bool:
        return self.camera is not None

    def setup(self) -> None:
        for band, config in SPECTRAL_CONFIG.items():
            self.spectral_channels[band] = LedAttributes(
                led=LED(config["pin"]) if config["pin"] is not None else None,
                exposure_time_us=config["exposure"],
                analogue_gain=config["gain"],
            )

        self.camera = Picamera2()
        self.set_resolution(high_res=False)

    def teardown(self) -> None:
        if self.camera is not None:
            self.camera.stop()
            self.camera = None
        for channel in self.spectral_channels.values():
            if channel.led is not None:
                channel.led.close()
        self.spectral_channels.clear()

    def set_resolution(self, high_res: bool) -> None:
        if self.camera is None:
            return

        self.camera.stop()
        size = (4608, 2592) if high_res else (800, 600)
        config = self.camera.create_preview_configuration(
            main={"size": size}, buffer_count=2
        )
        self.camera.configure(config)
        self.camera.set_controls(DEFAULT_CAMERA_SETTINGS)
        self.camera.start()

    def set_focus(self, value: float) -> None:
        if self.camera is None:
            return
        self.camera.set_controls({"AfMode": 0, "LensPosition": value})
        DEFAULT_CAMERA_SETTINGS["LensPosition"] = value

    def capture_preview_jpeg(self, quality: int = 40) -> str | None:
        if self.camera is None:
            return None
        frame = self.camera.capture_array("main")
        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        _, buffer = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return base64.b64encode(buffer).decode("utf-8")

    def set_exposures(self, exposures: dict[str, int]) -> None:
        for band, exposure in exposures.items():
            if band in self.spectral_channels:
                self.spectral_channels[band].exposure_time_us = exposure

    def acquire_standard_photo(self) -> list[tuple[str, np.ndarray]]:
        if self.camera is None:
            raise RuntimeError("Camera is not ready")
        self.camera.set_controls({"AeEnable": True, "AwbEnable": True})
        time.sleep(1.0)
        return [("standard", self.camera.capture_array("main"))]

    def acquire_spectral_cube(self) -> list[tuple[str, np.ndarray]]:
        if self.camera is None:
            raise RuntimeError("Camera is not ready")

        captured_layers = []
        self.camera.set_controls({
            "AeEnable": False,
            "AwbEnable": False,
            "ColourGains": (1.0, 1.0),
        })
        for band, channel in self.spectral_channels.items():
            with self.switch_lighting(channel):
                self.camera.set_controls({
                    "ExposureTime": channel.exposure_time_us,
                    "AnalogueGain": channel.analogue_gain,
                })
                time.sleep(0.2)
                captured_layers.append((band, self.camera.capture_array("main")))
        return captured_layers

    @staticmethod
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

    @staticmethod
    def export_data(
        layers: list[tuple[str, np.ndarray]], target_dir: str, mode: str
    ) -> None:
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