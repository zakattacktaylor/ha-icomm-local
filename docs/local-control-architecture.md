# Local control: provisioning once, native LAN afterward

Validated on an A. O. Smith HPTS-80, controller 5.4, iCOMM network firmware
bc2.11.4. Other models/versions require their own validation.

## Runtime

Home Assistant's `icomm_local` integration communicates directly with the heater
using Ayla's authenticated LAN callback protocol. Home Assistant runs the callback
listener, performs key exchange, requests fresh `superBlockDyn1` values and sends
validated `setBlockParameter` writes. The installation key is stored in the HA
config entry and backups. The heater stores its LAN-enable setting and key.

No vendor account, cloud API, cloud emulator, MQTT broker or NUC protocol service
is required for this tested runtime path. Block the heater's Internet access
while preserving its LAN access: an ordinary vendor identity response can disable
LAN access again. Do not use a router action that disconnects the device from
Wi-Fi or blocks its local network access.

## One-time setup and recovery

The provisioning method verified so far emulates the heater's cloud endpoint
locally. It supplies LAN-enable flags and a private installation key, answering
`lan.json` and, when necessary, delivering the cloud-privileged `PUT lanip.json`
configuration command. It does not require the real cloud to accept or enable
LAN access. Unknown-key notification recovery can prompt a fresh identity fetch
without a physical restart.

This step needs temporary, device-scoped routing to the Green's provisioning
service. Keep the service and its private profile for recovery, but stop it after
commissioning. A factory reset or lost key may require provisioning again.
We have not verified a non-spoofing setup route for this model.

The related device-agent route table distinguishes application and cloud
privileges: `GET property.json` is application-only, while `PUT lanip.json` is
cloud-only. This explains why the LAN application can read fresh properties even
though the same read returned 404 through cloud reverse-REST. See the
[agent route table](https://github.com/ddkity/Roomba1.4.3/blob/master/component/common/ayla/libada/client.c).

## Hardware evidence, November 11, 2026

- A local notification key, generated independently of the vendor, passed
  identity/bootstrap, UDP registration, notification acknowledgment and command
  fetch with routed Internet access blocked.
- The locally supplied LAN key enabled the existing HA integration and fresh
  local telemetry.
- HA changed the target from 130°F to 129°F and restored 130°F, confirming both
  from fresh LAN readback while Internet access was blocked. Mode stayed Hybrid
  (HA's generic `eco` label in this integration).
- With the emulation listeners stopped and Internet still blocked, reloading the
  HA integration recovered fresh LAN telemetry.
- An ordinary physical heater power cycle recovered fresh LAN telemetry with
  both Internet and the emulator unavailable, retaining the 130°F target and
  Hybrid mode.

A failed control attempt during a network transition was rolled back; the cloud
confirmed the 130°F baseline. Subsequent tests required successful local bootstrap
and post-provisioning LAN readback before any control request.

A 24–48-hour soak, gateway-reboot verification of the persistent router policy,
and an actual NUC power-off test remain separate acceptance checks. The NUC was
an observer/router-setup tool during the tests above; it did not serve protocol
traffic. Raw captures, appliance identities and keys remain private.
