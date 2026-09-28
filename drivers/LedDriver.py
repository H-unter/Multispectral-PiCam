import time
import threading
from gpiozero import DigitalOutputDevice


class LedDriver:
    """Driver for the 16-channel TLC5940 PWM LED breakout board on Raspberry Pi 5."""

    def __init__(
        self,
        sin_pin=10,    # Physical Pin 19
        sclk_pin=11,   # Physical Pin 23
        blank_pin=25,  # Physical Pin 22
        xlat_pin=24,   # Physical Pin 18
        gsclk_pin=18,  # Physical Pin 12
    ):
        self.sin = DigitalOutputDevice(sin_pin, initial_value=False)
        self.sclk = DigitalOutputDevice(sclk_pin, initial_value=False)
        self.blank = DigitalOutputDevice(blank_pin, initial_value=True)
        self.xlat = DigitalOutputDevice(xlat_pin, initial_value=False)
        self.gsclk = DigitalOutputDevice(gsclk_pin, initial_value=False)

        self.gs_values = [0] * 16
        self._running = False
        self._thread = None
        self._lock = threading.Lock()

    def set_channel(self, channel, brightness):
        """Set 12-bit PWM brightness (0 to 4095) for a single channel (0 to 15)."""
        if not 0 <= channel <= 15:
            raise ValueError("Channel must be between 0 and 15.")
        self.gs_values[channel] = max(0, min(4095, int(brightness)))

    def clear_all(self):
        """Set all 16 channels to 0."""
        self.gs_values = [0] * 16

    def update(self):
        """Shift 192 bits (MSB first, Channel 15 down to Channel 0) and latch."""
        with self._lock:
            for ch in range(15, -1, -1):
                val = self.gs_values[ch]
                for bit in range(11, -1, -1):
                    if (val >> bit) & 1:
                        self.sin.on()
                    else:
                        self.sin.off()
                    self.sclk.on()
                    self.sclk.off()

            # Blank outputs, latch new data with XLAT, then unblank
            self.blank.on()
            self.xlat.on()
            self.xlat.off()
            self.blank.off()

    def _pwm_worker(self):
        """Continuously clock 4096 GSCLK pulses per PWM cycle."""
        while self._running:
            with self._lock:
                self.blank.off()
                for _ in range(4096):
                    self.gsclk.on()
                    self.gsclk.off()
                self.blank.on()

    def start(self):
        """Start the background GSCLK PWM thread."""
        if not self._running:
            self._running = True
            self._thread = threading.Thread(target=self._pwm_worker, daemon=True)
            self._thread.start()

    def stop(self):
        """Stop the background PWM thread and disable all LED outputs."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self.blank.on()
        self.sin.close()
        self.sclk.close()
        self.blank.close()
        self.xlat.close()
        self.gsclk.close()


def test_slot0():
    """Main test routine for an LED connected to Slot 0 (OUT0)."""
    driver = LedDriver()
    driver.clear_all()
    driver.update()
    driver.start()

    print("Testing LED on Slot 0... Press Ctrl+C to stop.")
    try:
        while True:
            steps = [
                (0, "OFF (0%)"),
                (1024, "LOW (25%)"),
                (2048, "MED (50%)"),
                (4095, "MAX (100%)"),
            ]
            for level, label in steps:
                print(f"Slot 0 -> {label} [PWM = {level}/4095]")
                driver.set_channel(0, level)
                driver.update()
                time.sleep(1.5)
    except KeyboardInterrupt:
        print("\nStopping LedDriver and turning off outputs...")
    finally:
        driver.stop()


if __name__ == "__main__":
    test_slot0()