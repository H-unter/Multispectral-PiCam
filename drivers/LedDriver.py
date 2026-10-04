import time
import threading
from gpiozero import DigitalOutputDevice

DEFAULT_R2_OHMS = 390.0


class LedDriver:
    """
    Intuitive Raspberry Pi 5 driver for the SparkFun TLC5940 16-Channel Breakout.
    Automatically calculates I_max from the onboard 2.2k R1 resistor and optional parallel R2 resistor.
    """

    V_IREF = 1.24          # Internal bandgap reference voltage (V)
    CURRENT_MULT = 31.5    # TLC5940 current multiplier constant
    R1_OHMS = 2200.0       # Onboard R1 resistor (2.2 kOhm)
    SAFE_MAX_MA = 120.0    # Datasheet recommended maximum current per channel (mA)

    def __init__(
        self,
        r2_ohms=DEFAULT_R2_OHMS,
        sin_pin=10,        # Physical Pin 19
        sclk_pin=11,       # Physical Pin 23
        blank_pin=25,      # Physical Pin 22
        xlat_pin=24,       # Physical Pin 18
        gsclk_pin=18,      # Physical Pin 12
        vprg_pin=23,       # Physical Pin 16
        pwm_steps=256,     # 256 steps (8-bit) for fast, flicker-free software PWM
        auto_start=True,   # Automatically start the background PWM clock on init
    ):
        # 1. Calculate effective R_IREF and I_max (mA)
        if r2_ohms is None:
            self.r_iref_ohms = self.R1_OHMS
        else:
            if r2_ohms <= 0:
                raise ValueError("r2_ohms must be a positive resistance in ohms.")
            self.r_iref_ohms = (self.R1_OHMS * float(r2_ohms)) / (self.R1_OHMS + float(r2_ohms))

        self.max_current_ma = self.CURRENT_MULT * (self.V_IREF / self.r_iref_ohms) * 1000.0

        if self.max_current_ma > self.SAFE_MAX_MA + 1.0:
            raise ValueError(
                f"r2_ohms={r2_ohms} sets I_max to {self.max_current_ma:.1f} mA, "
                f"which exceeds the TLC5940 safe limit of {self.SAFE_MAX_MA} mA (min R2 is ~390 ohms)."
            )

        # 2. Initialize GPIO pins (BLANK=HIGH first so all outputs stay off during boot)
        self.blank = DigitalOutputDevice(blank_pin, initial_value=True)
        self.sin = DigitalOutputDevice(sin_pin, initial_value=False)
        self.sclk = DigitalOutputDevice(sclk_pin, initial_value=False)
        self.xlat = DigitalOutputDevice(xlat_pin, initial_value=False)
        self.gsclk = DigitalOutputDevice(gsclk_pin, initial_value=False)
        self.vprg = DigitalOutputDevice(vprg_pin, initial_value=False)

        self.pwm_steps = max(1, min(4096, int(pwm_steps)))
        self.gs_values = [0] * 16   # Grayscale PWM (0 to pwm_steps - 1)
        self.dc_values = [0] * 16   # Dot Correction (0 to 63); 0 on boot to protect LEDs

        self._needs_first_gs_clock = False
        self._running = False
        self._thread = None
        self._lock = threading.Lock()
        self._stop_lock = threading.Lock()
        self._closed = False

        # 3. Zero out hardware registers before enabling outputs
        self.update_dot_correction()
        self.update()

        if auto_start:
            self.start()

    # --- Context Manager Support (`with LedDriver() as driver:`) ---
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    # --- High-Level Intuitive Interface ---
    def set_led(self, channel, current_ma=None, brightness_pct=100.0, commit=True):
        """
        Configure a single LED channel by target current (mA) and PWM brightness (0-100%).
        If current_ma is omitted, uses the board's maximum current (self.max_current_ma).
        """
        self._validate_channel(channel)
        target_ma = self.max_current_ma if current_ma is None else float(current_ma)
        actual_ma = self.set_current_ma(channel, target_ma, commit=False)
        self.set_brightness_pct(channel, brightness_pct, commit=False)

        if commit:
            self.update_dot_correction()
            self.update()
        return actual_ma

    def solo_led(self, channel, current_ma=None, brightness_pct=100.0):
        """
        Turn OFF all other channels and drive ONLY the specified channel.
        Ideal when driving one LED at a time with different current limits.
        """
        self._validate_channel(channel)
        self.gs_values = [0] * 16
        self.dc_values = [0] * 16
        return self.set_led(channel, current_ma=current_ma, brightness_pct=brightness_pct, commit=True)

    def off(self, channel=None):
        """Turn off a specific channel, or all channels if channel is None."""
        if channel is None:
            self.gs_values = [0] * 16
        else:
            self._validate_channel(channel)
            self.gs_values[channel] = 0
        self.update()

    # --- Granular Current (Dot Correction) & PWM Methods ---
    def set_current_ma(self, channel, target_ma, commit=True):
        """Set a channel's analog constant-current limit in mA (via 6-bit Dot Correction)."""
        self._validate_channel(channel)
        if target_ma < 0:
            raise ValueError("target_ma cannot be negative.")
        dc_step = round((min(target_ma, self.max_current_ma) / self.max_current_ma) * 63)
        self.dc_values[channel] = max(0, min(63, int(dc_step)))
        if commit:
            self.update_dot_correction()
        return self.get_channel_current_ma(channel)

    def get_channel_current_ma(self, channel):
        """Return the actual quantized Dot Correction current (mA) for a channel."""
        self._validate_channel(channel)
        return self.max_current_ma * (self.dc_values[channel] / 63.0)

    def set_brightness_pct(self, channel, pct, commit=True):
        """Set a channel's PWM brightness from 0.0% to 100.0%."""
        self._validate_channel(channel)
        pct = max(0.0, min(100.0, float(pct)))
        raw_val = round((pct / 100.0) * (self.pwm_steps - 1))
        self.gs_values[channel] = raw_val
        if commit:
            self.update()

    def set_dot_correction(self, channel, dc_value, commit=False):
        """Set raw 6-bit Dot Correction step (0 to 63)."""
        self._validate_channel(channel)
        self.dc_values[channel] = max(0, min(63, int(dc_value)))
        if commit:
            self.update_dot_correction()

    def set_channel(self, channel, raw_pwm, commit=False):
        """Set raw Grayscale PWM step (0 to pwm_steps - 1)."""
        self._validate_channel(channel)
        self.gs_values[channel] = max(0, min(self.pwm_steps - 1, int(raw_pwm)))
        if commit:
            self.update()

    # --- Low-Level Hardware Shift Register Updates ---
    def update_dot_correction(self):
        """Shift 96 bits (16 x 6-bit MSB first) into the Dot Correction register."""
        with self._lock:
            self.blank.on()
            self.vprg.on()  # VPRG = HIGH -> Dot Correction Mode

            for ch in range(15, -1, -1):
                val = self.dc_values[ch]
                for bit in range(5, -1, -1):
                    if (val >> bit) & 1:
                        self.sin.on()
                    else:
                        self.sin.off()
                    self.sclk.on()
                    self.sclk.off()

            self.xlat.on()
            self.xlat.off()
            self.vprg.off()  # VPRG = LOW -> Return to Grayscale Mode
            self._needs_first_gs_clock = True

    def update(self):
        """Shift 192 bits (16 x 12-bit MSB first) into the Grayscale PWM register."""
        with self._lock:
            self.vprg.off()
            for ch in range(15, -1, -1):
                val = self.gs_values[ch]
                for bit in range(11, -1, -1):
                    if (val >> bit) & 1:
                        self.sin.on()
                    else:
                        self.sin.off()
                    self.sclk.on()
                    self.sclk.off()

            self.blank.on()
            self.xlat.on()
            self.xlat.off()

            if self._needs_first_gs_clock:
                self.sclk.on()
                self.sclk.off()
                self._needs_first_gs_clock = False

            self.blank.off()

    def _pwm_worker(self):
        gsclk_on = self.gsclk.on
        gsclk_off = self.gsclk.off
        blank_on = self.blank.on
        blank_off = self.blank.off
        steps = self.pwm_steps

        while self._running:
            with self._lock:
                blank_off()
                for _ in range(steps):
                    gsclk_on()
                    gsclk_off()
                blank_on()

    def start(self):
        """Start the background GSCLK thread."""
        if not self._running:
            self._running = True
            self._thread = threading.Thread(target=self._pwm_worker, daemon=True)
            self._thread.start()

    def stop(self):
        """Stop the background thread, blank all outputs, and release GPIO pins."""
        with self._stop_lock:
            if self._closed:
                return

            self._running = False
            if self._thread is not None:
                self._thread.join(timeout=1.0)
            with self._lock:
                self.blank.on()
                for pin in (self.sin, self.sclk, self.blank, self.xlat, self.gsclk, self.vprg):
                    pin.close()
                self._closed = True

    @staticmethod
    def _validate_channel(channel):
        if not 0 <= channel <= 15:
            raise ValueError("Channel must be between 0 and 15.")


def test_slot0():
    """Main test script for Slot 0 using the 390-ohm R2 configuration."""
    with LedDriver(r2_ohms=DEFAULT_R2_OHMS) as leds:
        print(f"Initialized LedDriver | R_IREF = {leds.r_iref_ohms:.1f} ohms | I_max = {leds.max_current_ma:.2f} mA")
        print("Testing Slot 0 current scaling & brightness... Press Ctrl+C to stop.\n")

        try:
            while True:
                # Step through target currents in mA at 100% PWM duty cycle
                for target_ma in [0, 5.0, 10.0, leds.max_current_ma]:
                    actual_ma = leds.solo_led(channel=0, current_ma=target_ma, brightness_pct=100)
                    dc_val = leds.dc_values[0]
                    print(f"Slot 0 -> Target: {target_ma:5.1f} mA | Actual: {actual_ma:5.2f} mA (DC={dc_val}/63)")
                    time.sleep(1.5)
        except KeyboardInterrupt:
            print("\nShutting down cleanly...")


if __name__ == "__main__":
    test_slot0()