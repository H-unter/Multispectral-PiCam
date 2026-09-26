# models/SensorProfile.py
import json
import warnings
from enum import Enum

OUT_OF_BOUNDS_LEEWAY_NM = 50

class SensorChannel(Enum):
    """Represents a either the Red, Green, or Blue channel of a camera sensor."""
    R = 1
    G = 2
    B = 3

class SensorSensitivityProfile:
    """
    Normalized RGB sensitivity curves for a camera sensor.

    The profile stores one sensitivity value per RGB channel and nanometer.
    """
    def __init__(self, profile_path: str):
        with open(profile_path, 'r') as f:
            data = json.load(f)
            
        self.sensor_name = data["sensor_name"]
        self.min_wave = data["min_wavelength"]
        self.max_wave = data["max_wavelength"]
        self.sensitivity_curves = data["normalized_response"]
        self.responses = self.sensitivity_curves  # Backward-compatible alias.

    def get_sensitivity(self, channel: SensorChannel, wavelength_nm: int | float) -> float:
        """
        Parameters:
        - channel: The sensor channel (R, G, or B) for which sensitivity is requested.
        - wavelength_nm: The wavelength in nanometers for which sensitivity is requested.
        Returns:
        - The normalized sensitivity for the specified channel at the wavelength.
        """
        target = int(wavelength_nm)
        is_out_of_bounds = not (self.min_wave <= target <= self.max_wave)
        is_within_leeway = (self.min_wave - OUT_OF_BOUNDS_LEEWAY_NM <= target <= self.max_wave + OUT_OF_BOUNDS_LEEWAY_NM)

        if is_out_of_bounds and not is_within_leeway:
            raise ValueError(f"Wavelength {target}nm is out of bounds for sensor '{self.sensor_name}' (valid range: {self.min_wave}-{self.max_wave}nm).")
        if is_out_of_bounds and is_within_leeway:
            warnings.warn(f"Wavelength {target}nm is out of bounds for sensor '{self.sensor_name}' (valid range: {self.min_wave}-{self.max_wave}nm). Using the nearest boundary response.", UserWarning)
            target = max(self.min_wave, min(target, self.max_wave))
        
        # Direct math lookup: e.g., 405nm - 400nm = Index 5
        index = target - self.min_wave

        return self.sensitivity_curves[channel.name][index]

    def get_response_at_wavelength(
        self, channel: SensorChannel, target_wavelength: int | float
    ) -> float:
        """Backward-compatible alias for :meth:`get_sensitivity`."""
        return self.get_sensitivity(channel, target_wavelength)

    def get_rgb_compensation_weights(
        self, wavelength_nm: int | float | None
    ) -> tuple[float, float, float]:
        """Return normalized inverse-sensitivity weights in R, G, B order."""
        if wavelength_nm is None:
            return (1 / 3, 1 / 3, 1 / 3)

        sensitivities = [
            max(self.get_sensitivity(channel, wavelength_nm), 1e-12)
            for channel in SensorChannel
        ]
        inverse_sensitivities = [1 / sensitivity for sensitivity in sensitivities]
        total = sum(inverse_sensitivities)
        return tuple(weight / total for weight in inverse_sensitivities)


# Keep the original name available for callers that already use it.
SensorProfile = SensorSensitivityProfile



if __name__ == "__main__":
    # Example usage
    profile = SensorSensitivityProfile("config/imx571_spectral_profile.json")
    channel = SensorChannel.R  # Example channel
    wavelength = 1000  # Example wavelength in nm
    sensitivity = profile.get_sensitivity(channel, wavelength)
    weights = profile.get_rgb_compensation_weights(wavelength)
    print(f"Sensitivity at {wavelength}nm for channel {channel}: {sensitivity}")
    print(f"RGB compensation weights at {wavelength}nm: {weights}")