"""Process-wide camera hardware instances shared across NiceGUI script runs."""

import atexit
import logging
import signal

from camera_hardware import CameraHardware
from config import CAMERA_CONFIG
from drivers.LedDriver import LedDriver

logger = logging.getLogger(__name__)

led_driver = LedDriver(r2_ohms=None)
hardware_instances = {
    definition.camera_id: CameraHardware(
        csi_port=definition.csi_port,
        led_driver=led_driver,
    )
    for definition in CAMERA_CONFIG
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
