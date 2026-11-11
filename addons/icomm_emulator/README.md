# iCOMM development service

This experimental add-on provides a bounded traffic capture/forwarder and a
separate local HTTPS/UDP emulator. Only one can listen at a time. It enables native LAN access for setup and recovery. Direct HA LAN reads,
setpoint control and physical-reboot recovery passed hardware tests with the
emulator stopped and Internet blocked. Stop this service after commissioning;
it is not required for normal operation. Community setup remains experimental.

See the repository [plan](../../docs/cloud-emulator-plan.md) and
[development procedure](../../docs/development-capture.md).

Configure a random management token of at least 24 characters and the exact
allowed source IPv4 addresses. Start the add-on manually. Only the authenticated
management API is active until a capture or emulator window starts. Private
profiles and captures contain appliance secrets. Keep all ports on the LAN.
