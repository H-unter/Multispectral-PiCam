"""Process-wide camera hardware instances shared across NiceGUI script runs."""

from camera_hardware import CameraHardware
from drivers.LedDriver import LedDriver

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
    for hardware in hardware_instances.values():
        hardware.teardown()
    led_driver.stop()
    _shutdown_complete = True
