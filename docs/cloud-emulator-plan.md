# Fully local cloud emulator: acceptance plan

The active architecture is a Green-hosted replacement for the heater's HTTPS,
UDP notification and DNS paths. The direct LAN callback integration is disabled.
See [runtime architecture](local-control-architecture.md) for the installed design.

## Completed evidence

- Decode, sign and generate notification packets using a locally owned key.
- Accept the tested legacy TLS handshake and preserve the device's XML framing.
- Complete local registration, notify/acknowledge, command fetch and telemetry.
- Handle the actual firmware's malformed plain-HTTP recovery ping separately
  from the authenticated management API.
- Confirm 130→129→130°F by fresh appliance telemetry through HA's normal service,
  with a controller-managed router configuration and heater Internet blocked.
- Run the emulator continuously on the Green with explicit autostart, boot
  startup and Supervisor watchdog configuration; bound diagnostics memory.
- Persist heater-scoped DNAT/SNAT in the router, not a temporary NUC/SSH process.
- Provide source-restricted local DNS with no upstream resolver; expected-name
  A, unknown-name NXDOMAIN and empty IPv6 answers tested; heater recovery passed.
- Confirm Heat Pump→Hybrid mode changes and steady 60-second telemetry without
  changing operating settings to trigger uploads.
- Save and inspect a recovery backup containing HA, private add-on data and code.
- Preserve the dashboard's water-heater entity ID when switching HA backend.

## Commissioning checks

Verify after each installation: private profile has no `lanip` field, backend
is continuously active and registered, telemetry is fresh, HA reports protocol
`emulated_cloud`, and commands are confirmed by new appliance telemetry. An
acknowledgement or queued command alone is insufficient. Confirm IPv4 and IPv6
Internet blocking and exact source scope of every router translation. Include
private add-on data and HA configuration in a recovery backup.

## Remaining acceptance work

- Record restart/reconnect evidence and installed versions for additional sites.
- Conduct extended soak and actual heater/Green/gateway power-loss tests.
- Test other firmware and models before widening compatibility claims.
- Simplify initial private profile acquisition; current onboarding still uses
  commissioned identity material, rather than universal out-of-box emulation.
- Package/review the community release and publish only when owner supplies
  the repository/account details. No credentials, captures or vendor code may
  be included in publication.

The original vendor app, account management, schedules, firmware updates and
utility/cloud services are outside the initial local runtime scope. Normal
operation uses no real vendor API or development NUC service.
