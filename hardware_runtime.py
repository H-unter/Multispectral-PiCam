"""Process-wide camera hardware instances shared across NiceGUI script runs."""

import atexit
import logging
import signal

from camera_hardware import CameraHardware
from drivers.LedDriver import LedDriver

logger = logging.getLogger(__name__)

led_driver = LedDriver(r2_ohms=None)
hardware_instances = {
    0: CameraHardware(camera_num=0, led_driver=led_driver),
    1: CameraHardware(camera_num=1, led_driver=led_driver),
}
_shutdown_complete = False


def shutdown() -> None:
    global _shutdown_complete
    if _shutdown_complete:
        return

    try:
        for hardware in hardware_instances.values():
            try:
                hardware.teardown()
            except Exception:
                logger.exception("Hardware shutdown failed")
    finally:
        try:
            led_driver.stop()
        except Exception:
            logger.exception("LED driver shutdown failed")
        _shutdown_complete = True


def _handle_exit_signal(signum, _frame) -> None:
    shutdown()
    if signum == signal.SIGINT:
        raise KeyboardInterrupt
    raise SystemExit(128 + signum)


atexit.register(shutdown)
signal.signal(signal.SIGINT, _handle_exit_signal)
signal.signal(signal.SIGTERM, _handle_exit_signal)
