# iCOMM Local for Home Assistant

An experimental local integration for A.O. Smith iCOMM NextGen heat-pump water
heaters. Developed against an HPTS-80 (controller firmware 5.4).

**Development status:** protocol codec tested against captured commands; direct
LAN provisioning is in progress. The config flow, callback listener, and entity
load on Home Assistant 2026.10.4; physical local control remains unverified. This
is not yet a ready-to-install community release.

## Intended architecture

Home Assistant runs the local callback service directly. No NUC, separate
bridge, MQTT broker, cloud account, or subscription is needed during normal
operation. A one-time provisioning procedure is required to enable the heater's
Ayla LAN interface with a locally generated key. That procedure is still being
validated; see [the provisioning checklist](docs/provisioning.md). Internet-independent operation must be verified before release.

- An authenticated, encrypted session delivers heater telemetry to HA.
- The heater receives LAN registration/notification heartbeats every 10 seconds.
- Commands are verified against fresh telemetry; queued requests expire.
- The water heater entity exposes target temperature and operating mode.
- Experimental tank-sensor mappings are disabled by default.

## Development

Python 3.13+; install `requirements-dev.txt` in a virtual environment, then:

```sh
python -m unittest discover -s tests -v
```

For a provisioned device, copy `custom_components/icomm_local` into Home
Assistant's `custom_components` directory and restart. Add **iCOMM Local** in
Settings → Devices & services, entering the heater IPv4 address, HA callback
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
