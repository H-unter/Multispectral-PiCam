from dataclasses import dataclass
from typing import Dict, Iterator, List
from models import SpectralChannel

class SpectralChannelCollection:
    """Manages a collection of SpectralChannels with custom queries and routing."""
    
    def __init__(self, channels: List['SpectralChannel']):
        self._channels: Dict[str, 'SpectralChannel'] = {ch.name: ch for ch in channels}

    def __getitem__(self, name: str) -> 'SpectralChannel':
        """Enables dictionary lookup syntax: my_system['green_led']"""
        return self._channels[name]

    def __iter__(self) -> Iterator['SpectralChannel']:
        """Enables for-loops directly on the object: for ch in my_system:"""
        return iter(self._channels.values())

    def __len__(self) -> int:
        """Enables checking the size: len(my_system)"""
        return len(self._channels)

    def by_wavelength(self) -> List['SpectralChannel']:
        """Returns channels sorted by wavelength"""
        def get_wavelength(ch):
            return ch.led.peak_wavelength_nm if ch.led is not None else float('inf')
            
        return sorted(self._channels.values(), key=get_wavelength)

    def __str__(self) -> str:
        """Defines how the object looks when you print() it."""
        lines = [f"ChannelCollection ({len(self)} channels):"]        
        for ch in self.by_wavelength():
            wavelength = f"{ch.led.peak_wavelength_nm}nm" if ch.led else "Dark Frame"
            lines.append(f"  • {ch.name:<12} | {wavelength:<10} | {ch.driver.drive_current_ma}mA")
            
        return "\n".join(lines)