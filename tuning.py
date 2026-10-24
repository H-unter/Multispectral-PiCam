#!/usr/bin/env python3
"""Calibrate per-channel LED currents and exposure times.

This is intentionally separate from the GUI. It produces a reviewable JSON
calibration file and does not modify config.py.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
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


def _capture_metric(
    hardware: CameraHardware,
    channel_name: str,
    exposure_us: int,
    current_ma: float,
    percentile: float,
) -> tuple[float, int]:
    channel = hardware.runtime_channels[channel_name].config
    channel.camera.exposure_time_us = min(
        exposure_us,
        hardware.max_exposure_time_us,
    )
    channel.driver.drive_current_ma = current_ma
    image, _, applied_exposure = hardware.capture_channel_test(channel_name)
    return float(np.percentile(image, percentile)), applied_exposure


def _binary_search_exposure(
    hardware: CameraHardware,
    channel_name: str,
    current_ma: float,
    target_metric: float,
    minimum_exposure_us: int,
    maximum_exposure_us: int,
    tolerance: float,
    percentile: float,
) -> dict[str, Any]:
    low = minimum_exposure_us
    high = maximum_exposure_us
    best_exposure = low
    best_mean = 0.0
    best_applied_exposure = 0
    applied_exposure = 0

    while low <= high:
        candidate = (low + high) // 2
        measured_metric, applied_exposure = _capture_metric(
            hardware,
            channel_name,
            candidate,
            current_ma,
            percentile,
        )
        logger.info(
            "  %s: exposure=%d us, applied=%d us, P%.0f=%.2f",
            channel_name,
            candidate,
            applied_exposure,
            percentile,
            measured_metric,
        )
        if abs(measured_metric - target_metric) < abs(best_mean - target_metric):
            best_exposure = applied_exposure
            best_mean = measured_metric
            best_applied_exposure = applied_exposure
        if abs(measured_metric - target_metric) <= tolerance:
            break
        if measured_metric < target_metric:
            low = candidate + 1
        else:
            high = candidate - 1

    return {
        "drive_current_ma": current_ma,
        "exposure_time_us": best_exposure,
        "metric": best_mean,
        "applied_exposure_us": best_applied_exposure,
    }


def _warm_start_exposure(
    hardware: CameraHardware,
    channel_name: str,
    current_ma: float,
    previous_exposure_us: int,
    target_metric: float,
    minimum_exposure_us: int,
    maximum_exposure_us: int,
    tolerance: float,
    percentile: float,
) -> dict[str, Any] | None:
    """Search around a previous exposure, returning None without a bracket."""
    previous_exposure_us = max(
        minimum_exposure_us,
        min(previous_exposure_us, maximum_exposure_us),
    )
    measured_metric, applied_exposure = _capture_metric(
        hardware,
        channel_name,
        previous_exposure_us,
        current_ma,
        percentile,
    )
    logger.info(
        "  %s warm start: exposure=%d, applied=%d, P%.0f=%.2f",
        channel_name,
        previous_exposure_us,
        applied_exposure,
        percentile,
        measured_metric,
    )
    if abs(measured_metric - target_metric) <= tolerance:
        return {
            "drive_current_ma": current_ma,
            "exposure_time_us": applied_exposure,
            "metric": measured_metric,
            "applied_exposure_us": applied_exposure,
        }

    if measured_metric < target_metric:
        low, high = previous_exposure_us, previous_exposure_us
        low_metric, high_metric = measured_metric, measured_metric
        while high < maximum_exposure_us and high_metric < target_metric:
            low, low_metric = high, high_metric
            high = min(maximum_exposure_us, max(high + 1, high * 2))
            high_metric, _ = _capture_metric(
                hardware, channel_name, high, current_ma, percentile
            )
    else:
        low, high = previous_exposure_us, previous_exposure_us
        low_metric, high_metric = measured_metric, measured_metric
        while low > minimum_exposure_us and low_metric > target_metric:
            high, high_metric = low, low_metric
            low = max(minimum_exposure_us, low // 2)
            low_metric, _ = _capture_metric(
                hardware, channel_name, low, current_ma, percentile
            )

    if not (low_metric <= target_metric <= high_metric):
        logger.warning(
            "  %s warm start could not bracket target; using full search",
            channel_name,
        )
        return None

    return _binary_search_exposure(
        hardware,
        channel_name,
        current_ma,
        target_metric,
        low,
        high,
        tolerance,
        percentile,
    )


def _current_grid(max_current_ma: float, minimum_current_ma: float) -> list[float]:
    """Return ascending current candidates for exposure calibration."""
    if minimum_current_ma <= 0 or max_current_ma <= 0:
        raise ValueError("Calibration currents must be positive")
    if minimum_current_ma > max_current_ma:
        raise ValueError("Starting current cannot exceed the channel maximum")
    values = [
        max_current_ma * 0.125,
        max_current_ma * 0.25,
        max_current_ma * 0.5,
        max_current_ma * 0.75,
        max_current_ma,
        minimum_current_ma,
    ]
    return sorted(
        {
            round(min(max_current_ma, max(minimum_current_ma, value)), 2)
            for value in values
        }
    )


def _calibrate_channel(
    hardware: CameraHardware,
    channel_name: str,
    max_current_ma: float,
    minimum_current_ma: float,
    target_metric: float,
    minimum_exposure_us: int,
    maximum_exposure_us: int,
    tolerance: float,
    percentile: float,
    previous_result: dict[str, Any] | None,
    reuse_previous: bool,
) -> dict[str, Any]:
    """Start at the safe current and increase it only when P90 is too low."""
    current_grid = _current_grid(max_current_ma, minimum_current_ma)
    previous_exposure = (
        previous_result.get("exposure_time_us")
        if isinstance(previous_result, dict)
        else None
    )

    fallback: dict[str, Any] | None = None
    for current_ma in current_grid:
        minimum_metric, minimum_applied = _capture_metric(
            hardware,
            channel_name,
            minimum_exposure_us,
            current_ma,
            percentile,
        )
        logger.info(
            "  %s current=%.2f mA minimum exposure P%.0f=%.2f",
            channel_name,
            current_ma,
            percentile,
            minimum_metric,
        )
        if minimum_metric > target_metric + tolerance:
            logger.info(
                "  %s remains too bright at minimum exposure at the starting current",
                channel_name,
            )
            return {
                "drive_current_ma": current_ma,
                "exposure_time_us": minimum_applied,
                "metric": minimum_metric,
                "applied_exposure_us": minimum_applied,
            }

        maximum_metric, maximum_applied = _capture_metric(
            hardware,
            channel_name,
            maximum_exposure_us,
            current_ma,
            percentile,
        )
        if maximum_metric < target_metric - tolerance:
            fallback = {
                "drive_current_ma": current_ma,
                "exposure_time_us": maximum_applied,
                "metric": maximum_metric,
                "applied_exposure_us": maximum_applied,
            }
            logger.warning(
                "  %s cannot reach target at %.2f mA and maximum exposure; increasing current",
                channel_name,
                current_ma,
            )
            continue

        result = None
        if (
            reuse_previous
            and isinstance(previous_exposure, (int, float))
            and previous_exposure > 0
            and isinstance(previous_result, dict)
            and math.isclose(
                float(previous_result.get("drive_current_ma", -1)),
                current_ma,
                rel_tol=0.01,
            )
        ):
            result = _warm_start_exposure(
                hardware,
                channel_name,
                current_ma,
                int(previous_exposure),
                target_metric,
                minimum_exposure_us,
                maximum_exposure_us,
                tolerance,
                percentile,
            )
        if result is None:
            result = _binary_search_exposure(
                hardware,
                channel_name,
                current_ma,
                target_metric,
                minimum_exposure_us,
                maximum_exposure_us,
                tolerance,
                percentile,
            )
        return result

    if fallback is None:
        raise RuntimeError(f"No current candidates available for {channel_name}")
    return fallback


def _calibration_is_compatible(
    calibration: dict[str, Any],
    *,
    percentile: float,
    output_size: tuple[int, int],
    crop: tuple[int, int, int, int] | None,
) -> bool:
    stored_percentile = calibration.get("percentile")
    if not isinstance(stored_percentile, (int, float)):
        return False
    return (
        calibration.get("target_metric") == "percentile_monochrome_intensity"
        and math.isclose(stored_percentile, percentile)
        and calibration.get("capture_resolution") == list(output_size)
        and calibration.get("crop") == (list(crop) if crop else None)
        and calibration.get("analysis_region") == "full_frame"
    )


def _load_previous_calibration(
    path: str,
    *,
    percentile: float,
    output_size: tuple[int, int],
    crop: tuple[int, int, int, int] | None,
) -> dict[str, Any] | None:
    try:
        with open(path, "r", encoding="utf-8") as calibration_file:
            calibration = json.load(calibration_file)
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("Could not reuse calibration %s: %s", path, error)
        return None
    if not isinstance(calibration, dict) or not _calibration_is_compatible(
        calibration,
        percentile=percentile,
        output_size=output_size,
        crop=crop,
    ):
        logger.warning("Previous calibration is incompatible; using full search")
        return None
    return calibration


def calibrate(
    hardware: CameraHardware,
    *,
    starting_exposure_us: int,
    maximum_exposure_us: int,
    target_mean: float,
    percentile: float,
    minimum_current_ma: float,
    minimum_exposure_us: int,
    tolerance: float,
    crop: tuple[int, int, int, int] | None,
    output_size: tuple[int, int],
    previous_calibration: dict[str, Any] | None = None,
    reuse_previous: bool = False,
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
    starting_current_channels = {
        channel_name: min(minimum_current_ma, max_current)
        for channel_name, max_current in max_current_channels.items()
    }

    baseline: dict[str, dict[str, float | int]] = {}
    for index, channel in enumerate(SPECTRAL_CHANNELS, start=1):
        logger.info(
            "[baseline %d/%d] %s at %d us, %.1f mA",
            index,
            len(SPECTRAL_CHANNELS),
            channel.name,
            starting_exposure_us,
            starting_current_channels[channel.name],
        )
        metric, applied = _capture_metric(
            hardware,
            channel.name,
            starting_exposure_us,
            starting_current_channels[channel.name],
            percentile,
        )
        baseline[channel.name] = {
            "metric": metric,
            "exposure_time_us": starting_exposure_us,
            "applied_exposure_us": applied,
        }
        logger.info(
            "  %s baseline mean=%.2f, applied=%d us",
            channel.name,
            metric,
            applied,
        )

    darkest_channel = min(baseline, key=lambda name: baseline[name]["metric"])
    logger.info(
        "Darkest baseline channel: %s (mean=%.2f)",
        darkest_channel,
        baseline[darkest_channel]["metric"],
    )
    results = {}
    for index, channel in enumerate(SPECTRAL_CHANNELS, start=1):
        logger.info(
            "[search %d/%d] optimizing %s",
            index,
            len(SPECTRAL_CHANNELS),
            channel.name,
        )
        previous_result = (
            previous_calibration.get("channels", {}).get(channel.name)
            if previous_calibration
            else None
        )
        results[channel.name] = _calibrate_channel(
            hardware,
            channel.name,
            max_current_channels[channel.name],
            starting_current_channels[channel.name],
            target_mean,
            minimum_exposure_us,
            maximum_exposure_us,
            tolerance,
            percentile,
            previous_result if isinstance(previous_result, dict) else None,
            reuse_previous,
        )
        logger.info(
            "  %s result: %d us, metric=%.2f",
            channel.name,
            results[channel.name]["exposure_time_us"],
            results[channel.name]["metric"],
        )

    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target_metric": "percentile_monochrome_intensity",
        "percentile": percentile,
        "analysis_region": "full_frame",
        "analysis_resolution": list(output_size),
        "requested_target_metric": target_mean,
        "minimum_current_ma": minimum_current_ma,
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
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Reuse a compatible calibration and skip the maximum-exposure pass",
    )
    parser.add_argument(
        "--previous-calibration",
        default="tuning/channel_calibration.json",
        help="Calibration file used by --fast",
    )
    parser.add_argument("--target-mean", type=float, default=180.0)
    parser.add_argument(
        "--percentile",
        type=float,
        default=90.0,
        help="Percentile of the centered analysis region to calibrate (default: 90)",
    )
    parser.add_argument("--starting-exposure-us", type=int, default=60_000)
    parser.add_argument(
        "--maximum-exposure-us",
        type=int,
        default=DEFAULT_MAX_EXPOSURE_TIME_US,
        help="Maximum exposure used during calibration (default: 1 second)",
    )
    parser.add_argument("--minimum-exposure-us", type=int, default=100)
    parser.add_argument(
        "--minimum-current-ma",
        type=float,
        default=10.0,
        help="Starting LED current; increase only if P90 cannot be reached (default: 10 mA)",
    )
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
    if args.percentile <= 0 or args.percentile > 100:
        parser.error("--percentile must be between 0 and 100")
    if args.minimum_exposure_us <= 0:
        parser.error("--minimum-exposure-us must be positive")
    if args.minimum_current_ma <= 0:
        parser.error("--minimum-current-ma must be positive")
    if args.maximum_exposure_us <= 0:
        parser.error("--maximum-exposure-us must be positive")
    if args.minimum_exposure_us > args.maximum_exposure_us:
        parser.error("--minimum-exposure-us cannot exceed --maximum-exposure-us")

    crop = _parse_crop(args.crop)
    resolution_parts = [int(part.strip()) for part in args.resolution.split(",")]
    if len(resolution_parts) != 2 or any(value <= 0 for value in resolution_parts):
        parser.error("--resolution must be WIDTH,HEIGHT with positive values")
    output_size = (resolution_parts[0], resolution_parts[1])
    previous_calibration = None
    if args.fast:
        previous_calibration = _load_previous_calibration(
            args.previous_calibration,
            percentile=args.percentile,
            output_size=output_size,
            crop=crop,
        )
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger.info(
        "Starting spectral-channel calibration (%s search)",
        "warm-start" if previous_calibration is not None else "full",
    )
    hardware = CameraHardware(csi_port=CAMERA_CONFIG[0].csi_port)
    try:
        hardware.setup()
        calibration = calibrate(
            hardware,
            starting_exposure_us=args.starting_exposure_us,
            maximum_exposure_us=args.maximum_exposure_us,
            target_mean=args.target_mean,
            percentile=args.percentile,
            minimum_current_ma=args.minimum_current_ma,
            minimum_exposure_us=args.minimum_exposure_us,
            tolerance=args.tolerance,
            crop=crop,
            output_size=output_size,
            previous_calibration=previous_calibration,
            reuse_previous=args.fast and previous_calibration is not None,
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
