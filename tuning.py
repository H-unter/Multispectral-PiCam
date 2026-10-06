#!/usr/bin/env python3
"""Calibrate per-channel exposure times at each LED's maximum safe current.

This is intentionally separate from the GUI. It produces a reviewable JSON
calibration file and does not modify config.py.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

import numpy as np

from camera_hardware import DEFAULT_MAX_EXPOSURE_TIME_US, CameraHardware
from config import CAMERA_CONFIG, SPECTRAL_CHANNELS

logger = logging.getLogger("tuning")


def _parse_crop(value: str | None) -> tuple[int, int, int, int] | None:
    if value is None:
        return None
    parts = [int(part.strip()) for part in value.split(",")]
    if len(parts) != 4:
        raise ValueError("Crop must be left,top,width,height")
    left, top, width, height = parts
    if left < 0 or top < 0 or width <= 0 or height <= 0:
        raise ValueError("Crop coordinates and dimensions must be positive")
    return left, top, width, height


def _capture_mean(
    hardware: CameraHardware,
    channel_name: str,
    exposure_us: int,
    current_ma: float,
) -> tuple[float, int]:
    channel = hardware.runtime_channels[channel_name].config
    channel.camera.exposure_time_us = min(
        exposure_us,
        hardware.max_exposure_time_us,
    )
    channel.driver.drive_current_ma = current_ma
    image, _, applied_exposure = hardware.capture_channel_test(channel_name)
    return float(np.mean(image)), applied_exposure


def _binary_search_exposure(
    hardware: CameraHardware,
    channel_name: str,
    current_ma: float,
    target_mean: float,
    minimum_exposure_us: int,
    maximum_exposure_us: int,
    tolerance: float,
) -> dict[str, Any]:
    low = minimum_exposure_us
    high = maximum_exposure_us
    best_exposure = low
    best_mean = 0.0
    best_applied_exposure = 0
    applied_exposure = 0

    while low <= high:
        candidate = (low + high) // 2
        measured_mean, applied_exposure = _capture_mean(
            hardware,
            channel_name,
            candidate,
            current_ma,
        )
        logger.info(
            "  %s: exposure=%d us, applied=%d us, mean=%.2f",
            channel_name,
            candidate,
            applied_exposure,
            measured_mean,
        )
        if abs(measured_mean - target_mean) < abs(best_mean - target_mean):
            best_exposure = applied_exposure
            best_mean = measured_mean
            best_applied_exposure = applied_exposure
        if abs(measured_mean - target_mean) <= tolerance:
            break
        if measured_mean < target_mean:
            low = candidate + 1
        else:
            high = candidate - 1

    return {
        "drive_current_ma": current_ma,
        "exposure_time_us": best_exposure,
        "mean": best_mean,
        "applied_exposure_us": best_applied_exposure,
    }


def calibrate(
    hardware: CameraHardware,
    *,
    starting_exposure_us: int,
    maximum_exposure_us: int,
    target_mean: float,
    minimum_exposure_us: int,
    tolerance: float,
    crop: tuple[int, int, int, int] | None,
    output_size: tuple[int, int],
) -> dict[str, Any]:
    if crop is not None:
        left, top, width, height = crop
        sensor_width, sensor_height = hardware.sensor_resolution
        if left + width > sensor_width or top + height > sensor_height:
            raise ValueError(
                f"Crop must fit within the {sensor_width}x{sensor_height} sensor"
            )
    logger.info(
        "Configuring calibration stream at %dx%d%s",
        output_size[0],
        output_size[1],
        f" with crop {crop}" if crop else "",
    )
    hardware.set_resolution(
        high_res=False,
        scaler_crop=crop,
        output_size=output_size,
    )
    hardware_exposure_limit_us = hardware.hardware_max_exposure_time_us
    maximum_exposure_us = min(maximum_exposure_us, hardware_exposure_limit_us)
    logger.info("Hardware exposure limit: %d us", hardware_exposure_limit_us)
    logger.info("Calibration exposure cap: %d us", maximum_exposure_us)
    if starting_exposure_us > maximum_exposure_us:
        starting_exposure_us = maximum_exposure_us

    max_current_channels = {
        channel.name: min(
            channel.led.max_current_ma if channel.led else hardware.led_driver.max_current_ma,
            hardware.led_driver.max_current_ma,
        )
        for channel in SPECTRAL_CHANNELS
    }

    baseline: dict[str, dict[str, float | int]] = {}
    for index, channel in enumerate(SPECTRAL_CHANNELS, start=1):
        logger.info(
            "[baseline %d/%d] %s at %d us, %.1f mA",
            index,
            len(SPECTRAL_CHANNELS),
            channel.name,
            starting_exposure_us,
            max_current_channels[channel.name],
        )
        mean, applied = _capture_mean(
            hardware,
            channel.name,
            starting_exposure_us,
            max_current_channels[channel.name],
        )
        baseline[channel.name] = {
            "mean": mean,
            "exposure_time_us": starting_exposure_us,
            "applied_exposure_us": applied,
        }
        logger.info(
            "  %s baseline mean=%.2f, applied=%d us",
            channel.name,
            mean,
            applied,
        )

    darkest_channel = min(baseline, key=lambda name: baseline[name]["mean"])
    logger.info(
        "Darkest baseline channel: %s (mean=%.2f)",
        darkest_channel,
        baseline[darkest_channel]["mean"],
    )
    maximum_means: dict[str, float] = {}
    maximum_applied_exposures: dict[str, int] = {}
    for index, channel in enumerate(SPECTRAL_CHANNELS, start=1):
        logger.info(
            "[maximum %d/%d] %s at %d us",
            index,
            len(SPECTRAL_CHANNELS),
            channel.name,
            maximum_exposure_us,
        )
        maximum_means[channel.name], maximum_applied_exposures[channel.name] = _capture_mean(
            hardware,
            channel.name,
            maximum_exposure_us,
            max_current_channels[channel.name],
        )
        logger.info(
            "  %s maximum mean=%.2f",
            channel.name,
            maximum_means[channel.name],
        )

    achievable_target = target_mean
    unable_to_reach = {
        name: mean
        for name, mean in maximum_means.items()
        if mean < target_mean - tolerance
    }
    logger.info(
        "Target mean: requested=%.2f",
        target_mean,
    )
    if unable_to_reach:
        logger.warning(
            "Channels below target at maximum exposure (they will remain at "
            "their maximum): %s",
            ", ".join(
                f"{name} ({mean:.2f})"
                for name, mean in unable_to_reach.items()
            ),
        )
    results = {}
    for index, channel in enumerate(SPECTRAL_CHANNELS, start=1):
        logger.info(
            "[search %d/%d] optimizing %s",
            index,
            len(SPECTRAL_CHANNELS),
            channel.name,
        )
        if maximum_means[channel.name] < achievable_target - tolerance:
            results[channel.name] = {
                "drive_current_ma": max_current_channels[channel.name],
                "exposure_time_us": maximum_applied_exposures[channel.name],
                "mean": maximum_means[channel.name],
                "applied_exposure_us": maximum_applied_exposures[channel.name],
            }
        else:
            results[channel.name] = _binary_search_exposure(
                hardware,
                channel.name,
                max_current_channels[channel.name],
                achievable_target,
                minimum_exposure_us,
                maximum_exposure_us,
                tolerance,
            )
        results[channel.name]["maximum_mean"] = maximum_means[channel.name]
        logger.info(
            "  %s result: %d us, mean=%.2f",
            channel.name,
            results[channel.name]["exposure_time_us"],
            results[channel.name]["mean"],
        )

    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target_metric": "mean_monochrome_intensity",
        "requested_target_mean": target_mean,
        "achievable_target_mean": achievable_target,
        "darkest_channel_at_start": darkest_channel,
        "starting_exposure_us": starting_exposure_us,
        "hardware_maximum_exposure_us": hardware_exposure_limit_us,
        "maximum_exposure_us": maximum_exposure_us,
        "crop": list(crop) if crop else None,
        "capture_resolution": list(output_size),
        "baseline": baseline,
        "channels": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tune spectral-channel exposure at maximum LED current."
    )
    parser.add_argument("--output", default="tuning/channel_calibration.json")
    parser.add_argument("--target-mean", type=float, default=180.0)
    parser.add_argument("--starting-exposure-us", type=int, default=60_000)
    parser.add_argument(
        "--maximum-exposure-us",
        type=int,
        default=DEFAULT_MAX_EXPOSURE_TIME_US,
        help="Maximum exposure used during calibration (default: 1 second)",
    )
    parser.add_argument("--minimum-exposure-us", type=int, default=100)
    parser.add_argument("--tolerance", type=float, default=2.0)
    parser.add_argument(
        "--resolution",
        default="800,450",
        help="Capture resolution as WIDTH,HEIGHT (default: 800,450)",
    )
    parser.add_argument(
        "--crop",
        help="Optional camera crop as left,top,width,height",
    )
    args = parser.parse_args()

    if len(CAMERA_CONFIG) != 1:
        parser.error("Tuning currently requires exactly one configured camera")
    if args.target_mean <= 0 or args.target_mean > 255:
        parser.error("--target-mean must be between 0 and 255")
    if args.minimum_exposure_us <= 0:
        parser.error("--minimum-exposure-us must be positive")
    if args.maximum_exposure_us <= 0:
        parser.error("--maximum-exposure-us must be positive")
    if args.minimum_exposure_us > args.maximum_exposure_us:
        parser.error("--minimum-exposure-us cannot exceed --maximum-exposure-us")

    crop = _parse_crop(args.crop)
    resolution_parts = [int(part.strip()) for part in args.resolution.split(",")]
    if len(resolution_parts) != 2 or any(value <= 0 for value in resolution_parts):
        parser.error("--resolution must be WIDTH,HEIGHT with positive values")
    output_size = (resolution_parts[0], resolution_parts[1])
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger.info("Starting spectral-channel calibration")
    hardware = CameraHardware(csi_port=CAMERA_CONFIG[0].csi_port)
    try:
        hardware.setup()
        calibration = calibrate(
            hardware,
            starting_exposure_us=args.starting_exposure_us,
            maximum_exposure_us=args.maximum_exposure_us,
            target_mean=args.target_mean,
            minimum_exposure_us=args.minimum_exposure_us,
            tolerance=args.tolerance,
            crop=crop,
            output_size=output_size,
        )
        output_path = os.path.abspath(args.output)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as output:
            json.dump(calibration, output, indent=2)
            output.write("\n")
        logger.info("Calibration written to %s", output_path)
        print(json.dumps(calibration, indent=2))
        print(f"\nCalibration written to {output_path}")
        return 0
    finally:
        hardware.teardown()


if __name__ == "__main__":
    sys.exit(main())
