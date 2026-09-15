from dataclasses import dataclass

@dataclass(kw_only=True)
class LEDAttributes:
    """Object representing the properties of the LED from its datasheet."""
    model_number: str
    peak_wavelength_nm: float
    min_wavelength_nm: float # defined by half power point
    max_wavelength_nm: float # defined by half power point
    max_current_ma: float
    viewing_angle_deg: float
    datasheet_url: str

