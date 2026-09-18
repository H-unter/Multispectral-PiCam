#!/usr/bin/python3
"""Command-line entry point for one camera acquisition."""

import os
import sys
from camera_hardware import CameraHardware

OUTPUT_DIR = "/images"
EXPORT_MODE = "jpg"
IS_MULTISPECTRAL = True


    
def main() -> None:
    hardware = CameraHardware()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    try:
        hardware.setup()
        if IS_MULTISPECTRAL:
            image = hardware.acquire_spectral_cube()
            if EXPORT_MODE in {"hypercube", "npz"}:
                image.export_npz(os.path.join(OUTPUT_DIR, "multispectral_cube.npz"))
            else:
                image.export_jpgs(OUTPUT_DIR)
        else:
            layers = hardware.acquire_standard_photo()
            hardware.export_data(layers, OUTPUT_DIR, EXPORT_MODE)
    except Exception as error:
        print(f"\n[ERROR] Failed multispectral block acquisition: {error}", file=sys.stderr)
        sys.exit(1)
    finally:
        hardware.teardown()


if __name__ == "__main__":
    main()