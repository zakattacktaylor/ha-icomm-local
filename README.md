# iCOMM Local for Home Assistant

An experimental local cloud replacement for A.O. Smith iCOMM NextGen heat-pump
water heaters, developed against an HPTS-80 (controller 5.4, network bc2.11.4).

The Home Assistant Green runs replacement HTTPS and UDP notification services.
The heater uses its normal cloud protocol, redirected inside the home; the HA
integration talks to the local service. The heater's vendor Internet access is
blocked. The development computer is not part of the runtime design.

**Validated:** registration, notifications, command fetches, telemetry and a
130→129→130°F target test through HA with persistent heater-scoped router rules
and Internet access blocked. Heat Pump→Hybrid mode changes, local DNS recovery,
and steady 60-second reporting also passed. Installation is still experimental and specific to
one tested firmware/model. Extended soak and physical power-loss tests remain.
The direct LAN callback route was unreliable and is retired for this deployment.

## Installation outline

1. Back up Home Assistant. Obtain the heater's private identity profile during
   commissioning; this is not a universal out-of-box onboarding replacement.
2. Install `addons/icomm_emulator`, set a strong management token and exact
   allowed heater/gateway IPv4 addresses. Provision its private profile through
   the authenticated API while continuous startup is disabled.
3. Configure persistent router redirects for **only the heater**, with return
   SNAT where the heater and Green share a subnet. Keep a separate IPv4/IPv6
   Internet block. See [runtime architecture](docs/local-control-architecture.md).
4. Enable the add-on's `emulator_autostart`, Start on boot and watchdog. It then
   runs continuously. Capture and bounded test modes cannot overlap emulation.
5. Copy `custom_components/icomm_local` to HA's custom components, restart HA,
   add **iCOMM Local → Local emulator add-on**, and supply the Green's address,
   management port 8787 and separate management token.

The service requires no vendor account or NUC process during operation. Initial
profile acquisition may require the original vendor setup and a private capture.
The vendor phone app is outside this offline control path. Physical heater
controls remain available.

Keep identity profiles, notification/LAN keys, management tokens, captures and
HA backups private. No owner credentials or vendor source bundles are included.
See the [add-on instructions](addons/icomm_emulator/README.md) and
[development capture history](docs/development-capture.md).

## Development

```sh
python -m unittest discover -s tests -q
```

Tests cover protocol framing, cryptography, replay checks, authenticated
management, command expiry/readback, startup, local DNS and scoped trial cleanup.
Live appliance validation remains essential; an HTTP acknowledgement alone does
not prove that the heater accepted a setting.
