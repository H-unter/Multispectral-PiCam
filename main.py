#!/usr/bin/python3
"""Command-line entry point for one camera acquisition."""

import argparse
import os
import sys
import cv2
from camera_hardware import CameraHardware
from file_naming import sanitize_filename_stem

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")
EXPORT_MODE = "hypercube" # can be "jpg", "hypercube", or "npz"
IS_MULTISPECTRAL = True


    
def main() -> None:
    parser = argparse.ArgumentParser(description="Capture an image or multispectral cube.")
    parser.add_argument(
        "--name",
        help="output filename stem; extensions such as .npz or .jpg are optional",
    )
    args = parser.parse_args()
    requested_name = args.name
    if requested_name is None and sys.stdin.isatty():
        requested_name = input("Output filename (leave blank for a timestamped name): ")
    output_name = sanitize_filename_stem(
        requested_name,
        "multispectral_cube" if IS_MULTISPECTRAL else "capture",
    )

    hardware = CameraHardware()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    try:
        hardware.setup()
        if IS_MULTISPECTRAL:
            image = hardware.acquire_spectral_cube()
            if EXPORT_MODE in {"hypercube", "npz"}:
                image.export_npz(os.path.join(OUTPUT_DIR, f"{output_name}.npz"))
            else:
                for index, band_name in enumerate(image.channel_names):
                    safe_band_name = sanitize_filename_stem(band_name, f"band{index}")
                    output_path = os.path.join(
                        OUTPUT_DIR, f"{output_name}_{safe_band_name}.jpg"
                    )
                    if not cv2.imwrite(output_path, image.channel(band_name)):
                        raise IOError(f"Could not write {output_path}")
        else:
            layers = hardware.acquire_standard_photo()
            if EXPORT_MODE == "jpg":
                output_path = os.path.join(OUTPUT_DIR, f"{output_name}.jpg")
                if not cv2.imwrite(output_path, layers[0][1]):
                    raise IOError(f"Could not write {output_path}")
            else:
                hardware.export_data(layers, OUTPUT_DIR, EXPORT_MODE)
    except Exception as error:
        print(f"\n[ERROR] Failed multispectral block acquisition: {error}", file=sys.stderr)
        sys.exit(1)
    finally:
        hardware.teardown()


if __name__ == "__main__":
    main()