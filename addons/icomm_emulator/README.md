# iCOMM local cloud service

Runs the heater's replacement HTTPS, UDP notification and optional authoritative
DNS services on Home Assistant. This is experimental, single-device software.

Configure a private management token (at least 24 characters) and exact allowed
heater/gateway IPv4 source addresses. With `emulator_autostart: false`, start the
add-on and provision its private profile using authenticated
`PUT http://GREEN:8787/emulator/profile`. The profile contains commissioned
identity XML and locally owned notification key, DSN/device identity, validated
report selection and optional `dns_hosts` mappings. Never publish it. Normal
cloud profiles omit the historical `lanip` provisioning field.

Once the private profile and persistent heater-only routing are ready, set
`emulator_autostart: true`, Start on boot and watchdog. Restart the add-on. The
emulator now runs continuously, rather than expiring after a test window.

| Port | Service |
| --- | --- |
| TCP 8787 | Bearer-authenticated management API |
| TCP 8444 | Source-restricted legacy-compatible HTTPS |
| TCP 8788 | Source-restricted legacy HTTP ping |
| UDP 55055/55056 | Source-restricted notification protocol |
| UDP/TCP 5354 | Source-restricted DNS when `dns_hosts` is provisioned |

A private DNS mapping points the expected cloud names to the router LAN IP so
that heater traffic traverses its persistent port translations. Unknown DNS
names return NXDOMAIN; there is no upstream resolver. Other household devices
must not be redirected to this DNS service.

The historical `GET /ping` on management port 8787 also returns an empty clock
response, restricted to allowed source addresses; all status/control/profile
routes require the management token. The separate TCP 8788 listener handles the
actual firmware's malformed HTTP framing and exposes no management functions.

Management routes include `/emulator/status`, `/emulator/control`,
`/emulator/notify` and `/emulator/stop`. Bounded `/emulator/start` accepts 10–900
seconds. Capture routes are development-only, limited to 10–300 seconds, and
refuse to run while emulation is active.

Back up the private add-on data together with the HA integration configuration.
Stopping/removing routing leaves the heater isolated from vendor Internet;
physical controls remain available. Disabling only the Internet block can let
the original cloud reconfigure the module. See the repository architecture notes
for commissioning evidence and current limitations.
