#!/usr/bin/python3
import os
import sys
import time
from picamera2 import Picamera2

OUTPUT_DIR = "./focus_calibration"

def ensure_directory(path: str):
    if not os.path.exists(path):
        os.makedirs(path)

def main():
    ensure_directory(OUTPUT_DIR)
    if not Picamera2.global_camera_info():
        print("\n[ERROR] Camera hardware connection failure", file=sys.stderr)
        sys.exit(1)
        
    try:
        camera = Picamera2()
        # Create a standard 1080p configuration for quick evaluation
        config = camera.create_preview_configuration(main={"size": (4608, 2592)})
        camera.configure(config)
        
        # Enable auto exposure so we can actually see the target
        camera.set_controls({"AeEnable": True, "AwbEnable": True})
        camera.start()
        
        print("Allowing ISP to meter the scene...")
        time.sleep(2.0)
        
        # Define the sweep range (Diopters: 0.0 is infinity, 10.0 is ~10cm)
        focus_steps = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        
        print("\nStarting Focus Sweep...")
        
        for focus_val in focus_steps:
            print(f"Moving lens to position: {focus_val} diopters...")
            
            # Command the VCM to move the lens to the absolute position
            camera.set_controls({
                "AfMode": 0,          # 0 = Manual Focus lock
                "LensPosition": focus_val
            })            
            time.sleep(0.5) 
            # Capture directly to file
            filename = os.path.join(OUTPUT_DIR, f"focus_step_{focus_val:.1f}.jpg")
            camera.capture_file(filename)
            print(f" Saved: {filename}")
            
        print("\n[SUCCESS] Sweep complete. Check the 'focus_calibration' folder to find the sharpest image!")

    except Exception as e:
        print(f"\n[ERROR] Focus sweep failed: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        camera.stop()

if __name__ == "__main__":
    main()