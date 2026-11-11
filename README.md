# iCOMM Local for Home Assistant

An experimental local-control project for A.O. Smith iCOMM NextGen heat-pump water
heaters. Developed against an HPTS-80 (controller firmware 5.4).

**Development status:** native LAN reads and a 130→129→130°F target test passed
on Home Assistant Green with the heater's Internet access blocked. Fresh LAN
readback also recovered after an integration reload and a physical heater reboot
while the provisioning server was stopped. This remains an experimental,
single-model project rather than a broadly validated community release.

## Architecture

The Green-hosted local cloud emulator is a **one-time provisioning and recovery
tool**: it enables the heater's native LAN API and supplies a private key. Normal
operation uses Home Assistant's LAN callback integration directly; it needs no
active proxy, emulator, vendor account or NUC service. Keep the heater's Internet
access blocked so vendor configuration does not disable LAN access again.

See the [current architecture and hardware evidence](docs/local-control-architecture.md)
and [provisioning/development procedure](docs/development-capture.md). The
[original full-cloud-emulation plan](docs/cloud-emulator-plan.md) records the
research path that led to this simpler runtime.

## Development

Python 3.13+; install `requirements-dev.txt` in a virtual environment, then:

```sh
python -m unittest discover -s tests -v
```

For a provisioned device, copy `custom_components/icomm_local` into Home
Assistant's `custom_components` directory and restart. Add **iCOMM Local** in
Settings → Devices & services, choose **Previously provisioned LAN key**, and enter the heater IPv4 address, HA callback
IPv4 address, LAN key/key ID, and callback port (default 8888). Reserve both
IP addresses. Keep callback traffic on a trusted LAN; no Internet port forwards.
Only one local controller should manage the heater's callback session.

The initial control limit is 95–130°F. A lower configurable maximum is supported.
Higher targets, firmware updates, registration changes, and fault resets are
not exposed. Electric and Vacation use a one-day duration in this preview;
Vacation temporarily lowers the heater's target to approximately 50°F. Switching
back to Hybrid restores the prior normal target on the tested heater.

## Privacy and security

The LAN key is stored in Home Assistant's config entry and backups; treat it as
an appliance credential. It is sent to the heater only during provisioning, and
used to derive AES-CBC/HMAC-SHA256 session keys afterward. Incoming updates must
pass signature and sequence validation, and originate from the configured
heater IPv4 address. This is the vendor's legacy protocol, not a claim that it
meets modern TLS security expectations.

Do not publish credentials, tokens, raw cloud captures, DSNs, serial numbers,
Wi-Fi details, or private keys. This repository contains synthetic test fixtures
and generic protocol examples only. Deleting the HA integration stops callbacks;
it does not erase the heater's provisioned LAN key. Preserve the key for recovery.

## Credits

Protocol discoveries and prior implementation references:

- [ericboehs/aosmith-water-heater](https://github.com/ericboehs/aosmith-water-heater)
- [deiger/AirCon](https://github.com/deiger/AirCon)
- [bdr99/py-aosmith](https://github.com/bdr99/py-aosmith) for the cloud API used
  during characterization; this integration does not use that API at runtime.

This is an independent community project, unaffiliated with A.O. Smith or Ayla.

Read-only findings about the embedded web server are in [HTTP surface observations](docs/http-surface.md).

The app-side metadata investigation is documented in [Android app analysis](docs/app-analysis.md).
