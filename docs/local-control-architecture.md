# Local cloud replacement on Home Assistant

The selected runtime is the heater's normal cloud protocol served locally.
The direct LAN callback integration is disabled after acknowledged temperature
writes failed to change the heater reliably. Successful LAN reads are not
sufficient evidence of reliable control.

## Runtime

```text
HA water-heater entity → authenticated local management API
                              ↓
                    Green HTTPS/UDP emulator
                              ↕
                  persistent heater-only NAT
                              ↕
                         water heater
```

The Green serves local identity, notification registration/keepalives, command
fetches, validated target/mode commands and temperature uploads. There is no
upstream network client in the emulator or its DNS service. The capture relay
is a separate, mutually exclusive development tool.

The private profile contains identity XML, a locally owned notification key,
report-selection configuration and optional local DNS mappings. Production
profiles omit `lanip`; no LAN key provisioning, callback polling or LAN reverse
property reads are needed. Experimental reverse-property reads are off by
default because the cloud request context rejected them.

## Persistent router configuration

Use fixed DHCP addresses for the heater and Green. These rules match only the
heater's source IPv4 address and LAN ingress interface; never bind the redirects
to a WAN interface. Retain the independent heater-only IPv4/IPv6 Internet block.

| Heater destination | Local destination on Green | Purpose |
| --- | --- | --- |
| TCP 443 | TCP 8444 | Replacement cloud HTTPS |
| TCP 80 | TCP 8788 | Legacy recovery ping |
| UDP 55055–55056 | Same UDP ports | Notifications and registration |
| UDP/TCP 53 | UDP/TCP 5354 | Heater-specific authoritative DNS |

For same-subnet routing, pair these with source-scoped return SNAT from the
heater to those Green ports, translating the source to the gateway's LAN IP.
The reviewed installation uses controller-managed UniFi DNAT/SNAT rules, with
kernel counters verified. Temporary SSH-installed trial rules are not runtime
configuration. No global firewall migration is required.

The local DNS profile maps only the expected OEM HTTPS hostname and ANS hostname
to the **gateway LAN IP**, not the Green: traffic must traverse the gateway's
port translation. The DNS service never forwards requests; unknown hosts return
NXDOMAIN and IPv6 questions receive no address. DNS interception matches only
the heater, so other devices retain their existing DNS behavior.

## Startup and confirmation

`emulator_autostart: true` starts continuous emulation from the private profile
on add-on startup. Enable Start on boot and the Supervisor watchdog. The bounded
management start API remains limited to 10–900 seconds and cannot request an
unlimited trial. Profile replacement is refused while emulation is active.

The HA entity requires a registered local session and telemetry younger than
180 seconds. The 60-second reporting interval was validated with unchanged
temperature values at intervals of 61.7 and 60.0 seconds; the availability window
permits network jitter. A restarted backend with no telemetry cannot
reuse the HA client's cached reading as a fresh state.

Commands are delivered once, expire after 30 seconds and require newer telemetry
with the requested target or mode before confirmation. Notifications are retried
while a command is pending; empty command polls maintain the local connection.
Event storage is bounded. Identity/capture material stays in add-on private data.

## Evidence and remaining validation

The Green service completed registration, notification acknowledgement, HTTPS
command fetching and telemetry with vendor Internet blocked. HA's normal target
service passed 130→129→130°F through controller-managed routing. The LAN entry
was disabled throughout this test. The heater was left at 130°F Hybrid. Final HA tests after local DNS commissioning
confirmed both 129→130°F and Heat Pump→Hybrid with fresh readback.

Source-restricted local DNS was checked for an expected A answer, unknown-name
NXDOMAIN, and no IPv6 answer. Restart/reconnect testing and the final installed
configuration are recorded in the installation notes. A software restart is
not a substitute for an actual full power-loss test. Extended soak, other heater
models/firmware, and community onboarding are separate acceptance work.
