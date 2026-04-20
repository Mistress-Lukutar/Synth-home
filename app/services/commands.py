"""Centralized command constants for ZigbeeHUB device actions."""


class DeviceCommand:
    """String constants used as the ``cmd`` / ``action`` field when talking
    to the Zigbee hub firmware over the serial protocol.
    """

    ON = "on"
    OFF = "off"
    TOGGLE = "toggle"
    LEVEL = "level"
    COLOR = "color"
    COLOR_CT = "color_ct"
    READ_ATTR = "read_attr"
