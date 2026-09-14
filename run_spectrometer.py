#!/usr/bin/python3
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from NIRS import NIRS

def execute_hardware_scan():
    """RESPONSIBILITY: Pure hardware communication and data capture."""
    # Instantiating connects immediately to the device over USB HID
    print("Connecting to TI DLP NIRscan Nano...")
    scanner = NIRS()
    scanner.clear_error_status()  # (Check NIRS.py for the exact method name!)
    print("Energising lamp and executing spectral scan block...")
    # The scan method handles micromirror matrix transformations and reads the ADC
    raw_results = scanner.scan()
    
    return raw_results

def main():
    # Guardrail: USB HID raw register access requires root access on Linux
    if os.geteuid() != 0:
        print("[ERROR] Script must be executed with sudo privileges to access USB ports.", file=sys.stderr)
        sys.exit(1)
        
    try:
        # 1. Acquire raw dictionary matrices from the hardware
        raw_data = execute_hardware_scan()
        
        # 2. Extract the three parallel numerical arrays
        wavelengths = np.array(raw_data['wavelength'])
        intensities = np.array(raw_data['intensity'])
        references = np.array(raw_data['reference'])
        
        # 3. Data Science Processing: Normalize to true Reflectance and Absorbance
        # Values range from 0.0 to 1.0 representing physical reflectance
        reflectance = intensities / references
        absorbance = -np.log10(reflectance)
        
        # 4. Display sample verification details
        print(f"\n[SUCCESS] Captured {len(wavelengths)} spectral data points!")
        print(f"Spectral Range: {wavelengths[0]:.1f} nm to {wavelengths[-1]:.1f} nm")
        
        print("\nFirst 5 Sample Matrix Rows:")
        print("Wavelength (nm) | Raw Intensity | Ref Baseline | Absorbance")
        print("-" * 58)
        for i in range(5):
            print(f"  {wavelengths[i]:.2f} nm  |  {intensities[i]:6d}     |  {references[i]:6d}     |  {absorbance[i]:.4f}")

    except Exception as e:
        print(f"\n[FATAL] Hardware acquisition failure: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()