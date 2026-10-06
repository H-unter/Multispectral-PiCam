#!/usr/bin/python3
"""Low-level camera, lighting, acquisition, and export operations."""

import base64
import logging
import os
import threading
import time
from contextlib import contextmanager
from typing import Callable

import cv2
import numpy as np
from picamera2 import Picamera2

from config import (
    DEFAULT_CAMERA_SETTINGS,
    SPECTRAL_CHANNELS,
)
from drivers.LedDriver import DEFAULT_R2_OHMS, LedDriver
from models import (
    CameraSettings,
    MultispectralImage,
    SensorSensitivityProfile,
    SpectralChannel,
)

logger = logging.getLogger(__name__)

class RuntimeChannel:
    """Bind a spectral-channel configuration to its TLC5940 output."""

    def __init__(self, config: SpectralChannel) -> None:
        self.config = config

class CameraHardware:
    """Encapsulates the camera and lighting hardware, providing methods for setup, capture, and export."""
    def __init__(
        self,
        csi_port: int,
        sensitivity_profile: SensorSensitivityProfile | None = None,
        led_driver: LedDriver | None = None,
    ) -> None:
        self.camera: Picamera2 | None = None
        self.csi_port = csi_port
        self.focus_max = 0.0
        self.led_driver = led_driver or LedDriver(r2_ohms=DEFAULT_R2_OHMS)
        self._owns_led_driver = led_driver is None
        self._setup_lock = threading.Lock()
        self.camera_settings = CameraSettings(**vars(DEFAULT_CAMERA_SETTINGS))
        self.runtime_channels: dict[str, RuntimeChannel] = {}
        self.camera_resolution: tuple[int, int] | None = None
        self.sensor_resolution = (4608, 2592)
        self.scaler_crop: tuple[int, int, int, int] | None = None
        profile_path = os.path.join(
            os.path.dirname(__file__), "config", "imx571_spectral_profile.json"
        )
        self.sensitivity_profile = sensitivity_profile or SensorSensitivityProfile(
            profile_path
        )

    @property
    def is_ready(self) -> bool:
        return self.camera is not None

    @staticmethod
    def _control_maximum(control_range) -> float:
        """Extract the maximum from Picamera2 scalar or tuple control ranges."""
        if isinstance(control_range, (tuple, list)):
            if len(control_range) < 2:
                raise ValueError(f"Invalid camera control range: {control_range!r}")
            return CameraHardware._control_maximum(control_range[1])
        return float(control_range)

    @property
    def max_exposure_time_us(self) -> int:
        """Return the active camera mode's effective exposure-time ceiling."""
        if self.camera is None:
            raise RuntimeError("Camera is not ready")

        exposure_max = self._control_maximum(
            self.camera.camera_controls["ExposureTime"]
        )
        frame_duration_max = self._control_maximum(
            self.camera.camera_controls["FrameDurationLimits"]
        )
        return int(min(exposure_max, frame_duration_max))

    def setup(self) -> None:
        with self._setup_lock:
            if self.camera is not None:
                return

            try:
                for channel_config in SPECTRAL_CHANNELS:
                    runtime_channel = RuntimeChannel(channel_config)
                    self.runtime_channels[channel_config.name] = runtime_channel

                camera_info = Picamera2.global_camera_info()
                matching_cameras = [
                    info for info in camera_info
                    if info.get("Location") == self.csi_port
                ]
                if len(matching_cameras) != 1:
                    raise RuntimeError(
                        f"Expected one camera at CSI location {self.csi_port}, "
                        f"found {len(matching_cameras)}"
                    )

                self.camera = Picamera2(camera_num=matching_cameras[0]["Num"])
                _focus_min, self.focus_max, _focus_default = self.camera.camera_controls[
                    "LensPosition"
                ]
                self.focus_max = float(self.focus_max)
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

        try:
            self.led_driver.off()
        except Exception:
            logger.exception("LED shutdown failed")
        finally:
            if self._owns_led_driver:
                self.led_driver.stop()
        self.runtime_channels.clear()

    def set_resolution(
        self,
        high_res: bool,
        scaler_crop: tuple[int, int, int, int] | None = None,
    ) -> None:
        if self.camera is None:
            return

        self.camera.stop()
        size = (
            (scaler_crop[2], scaler_crop[3])
            if high_res and scaler_crop is not None
            else (4608, 2592) if high_res else (800, 450)
        )
        self.camera_resolution = size
        self.scaler_crop = scaler_crop if high_res else None
        config = self.camera.create_preview_configuration(
            main={"size": size, "format": "RGB888"}, buffer_count=2
        )
        self.camera.configure(config)
        if scaler_crop is not None:
            self.camera.set_controls({"ScalerCrop": scaler_crop})
        # Apply the default settings dataclass here
        self.camera.set_controls(self.camera_settings.to_control_dict())
        self.camera.start()

    def set_focus(self, value: float) -> None:
        if self.camera is None:
            return

        # Update the dataclass in memory so it persists
        self.camera_settings.lens_position = max(
            0.0,
            min(self.focus_max, float(value)),
        )
        
        # Apply the updated setting
        self.camera.set_controls(self.camera_settings.to_control_dict())

    def set_active_channel(self, channel_name: str | None) -> None:
        """Enable one configured channel LED and switch all other LEDs off."""
        if channel_name is not None and channel_name not in self.runtime_channels:
            raise ValueError(f"Unknown spectral channel: {channel_name}")

        if channel_name is None:
            self.led_driver.off()
            return

        channel = self.runtime_channels[channel_name].config
        self.led_driver.solo_led(
            channel.driver.tlc5940_channel,
            current_ma=self._channel_current_ma(channel),
        )

    def apply_channel_preview_settings(self, channel_name: str) -> None:
        """Apply one channel's LED and manual camera settings for a test frame."""
        if self.camera is None:
            raise RuntimeError("Camera is not ready")
        if channel_name not in self.runtime_channels:
            raise ValueError(f"Unknown spectral channel: {channel_name}")

        channel = self.runtime_channels[channel_name].config
        self.set_active_channel(channel_name)
        controls = {
            "AeEnable": False,
            "AwbEnable": False,
            **channel.camera.to_control_dict(),
        }
        if "ExposureTime" in controls:
            controls["ExposureTime"] = min(
                int(controls["ExposureTime"]),
                self.max_exposure_time_us,
            )
        self.camera.set_controls(controls)

    def capture_channel_test(self, channel_name: str) -> tuple[np.ndarray, int, int]:
        """Capture a settled channel frame and return image plus exposure metadata."""
        self.apply_channel_preview_settings(channel_name)
        if self.camera is None:
            raise RuntimeError("Camera is not ready")

        channel = self.runtime_channels[channel_name].config
        wavelength_nm = channel.led.peak_wavelength_nm if channel.led else None
        requested_exposure = min(
            int(channel.camera.exposure_time_us or 0),
            self.max_exposure_time_us,
        )
        selected_frame = None
        applied_exposure = requested_exposure

        for _ in range(3):
            frame = self.camera.capture_array("main")
            metadata = self.camera.capture_metadata()
            applied_exposure = int(metadata.get("ExposureTime", 0))
            selected_frame = frame
            if applied_exposure == requested_exposure:
                break

        if selected_frame is None:
            raise RuntimeError("Camera returned no test frame")
        monochrome = self.sensitivity_weighted_rgb(
            selected_frame,
            self.sensitivity_profile,
            wavelength_nm,
        )
        return (
            np.rint(np.clip(monochrome, 0, 255)).astype(np.uint8),
            requested_exposure,
            applied_exposure,
        )

    def set_channel_current(self, channel_name: str, current_ma: float) -> None:
        if channel_name not in self.runtime_channels:
            raise ValueError(f"Unknown spectral channel: {channel_name}")

        channel = self.runtime_channels[channel_name].config
        channel.driver.drive_current_ma = self._channel_current_ma(channel, current_ma)
        self.led_driver.set_current_ma(
            channel.driver.tlc5940_channel,
            channel.driver.drive_current_ma,
        )

    def _channel_current_ma(
        self,
        channel: SpectralChannel,
        current_ma: float | None = None,
    ) -> float:
        requested_ma = (
            channel.driver.drive_current_ma
            if current_ma is None
            else float(current_ma)
        )
        led_limit = channel.led.max_current_ma if channel.led else self.led_driver.max_current_ma
        return min(requested_ma, float(led_limit), self.led_driver.max_current_ma)

    def capture_preview_jpeg(self, quality: int = 40) -> str | None:
        if self.camera is None:
            return None
        frame = self.camera.capture_array("main")
        _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return base64.b64encode(buffer).decode("utf-8")

    @staticmethod
    def sensitivity_weighted_rgb(
        frame: np.ndarray,
        sensitivity_profile: SensorSensitivityProfile,
        wavelength_nm: int | float | None,
    ) -> np.ndarray:
        """Combine RGB values using inverse sensor sensitivity at a wavelength."""
        if frame.ndim != 3 or frame.shape[-1] not in (3, 4):
            raise ValueError(
                f"Expected an RGB or four-channel frame, received shape {frame.shape}"
            )
        weights = np.asarray(
            sensitivity_profile.get_rgb_compensation_weights(wavelength_nm),
            dtype=np.float32,
        )
        return np.sum(frame[..., -3:] * weights, axis=-1)

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
        for band_name, rt_channel in self.runtime_channels.items():
            with self.switch_lighting(rt_channel):
                # Pass the channel's specific CameraSettings dataclass directly
                channel_controls = rt_channel.config.camera.to_control_dict()
                if "ExposureTime" in channel_controls:
                    channel_controls["ExposureTime"] = min(
                        int(channel_controls["ExposureTime"]),
                        self.max_exposure_time_us,
                    )
                self.camera.set_controls(channel_controls)
                time.sleep(0.2)
                frame = self.camera.capture_array("main")
                if process_frame is not None:
                    processed_frame = process_frame(frame)
                else:
                    wavelength_nm = (
                        rt_channel.config.led.peak_wavelength_nm
                        if rt_channel.config.led is not None
                        else None
                    )
                    processed_frame = self.sensitivity_weighted_rgb(
                        frame, self.sensitivity_profile, wavelength_nm
                    )
                captured_layers.append(
                    (
                        band_name,
                        np.rint(np.clip(processed_frame, 0, 255)).astype(np.uint8),
                    )
                )
                
        image_height, image_width = captured_layers[0][1].shape
        resolution = self.camera_resolution or (image_width, image_height)
        return MultispectralImage.from_layers(
            captured_layers,
            channels=[channel.config for channel in self.runtime_channels.values()],
            metadata={
                "camera": {
                    "resolution": list(resolution),
                    "sensor_resolution": list(self.sensor_resolution),
                    "scaler_crop": list(self.scaler_crop)
                    if self.scaler_crop is not None
                    else None,
                }
            },
        )

    @contextmanager
    def switch_lighting(self, rt_channel: RuntimeChannel):
        channel = rt_channel.config
        self.led_driver.solo_led(
            channel.driver.tlc5940_channel,
            current_ma=self._channel_current_ma(channel),
        )
        try:
            yield
        finally:
            self.led_driver.off(channel.driver.tlc5940_channel)

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