# iCOMM protocol observations

Research notes, not a ready-to-install local integration. Verified on an A.O.
Smith HPTS-80 200 202172000, firmware 5.4, November 11, 2026.

## Cloud API

The app uses GraphQL over HTTPS. Existing client:
https://github.com/bdr99/py-aosmith

Reviewed client uses `https://r2.wh8.co/graphql`, headers `brand: icomm`,
`version: 14.1.0`, and bearer authentication. Its login query takes a `passcode`
formed by Base64 encoding URL-encoded JSON containing email, password, locale.
This encoding is not encryption; TLS protects transport. Never publish tokens,
passcodes, raw account responses, or unfiltered captures.

Verified operations:

- Login and device query, including pending flags and supported modes.
- Extended device query: active/historical alerts, schedule data, Wi-Fi status,
  demand-response state, and other fields. Reading a field does not establish
  support for changing it locally.
- `updateMode(junctionId: String!, mode: ModeInput!)`: Heat Pump, Electric,
  Vacation, Hybrid. Electric/Vacation tested with `days: 1`.
- Schema introspection request returned HTTP 400; complete API coverage has
  not been established. No resets, deregistration, firmware updates, or
  notification-setting changes tested.

## Heater-facing protocol

Published prior research:
https://github.com/ericboehs/aosmith-water-heater/tree/main/icomm

Our bounded relay forwards requests and cloud replies unchanged, while recording
HTTP streams privately. Heater accepts a self-signed RSA/SHA256 certificate with
TLS 1.2, DHE-RSA-AES256-SHA and 2048-bit DH parameters. Upstream hostname and
certificate verification remain enabled, using a separately verified legacy CA.
This finding alone does not constitute a cloud-free replacement.

Observed `setBlockParameter` values:

| Action | Hex frame |
|---|---|
| Target 129°F | `BD 40 08 0B 06 35 E4 38` |
| Target 130°F | `BD 40 08 0B 06 36 72 34` |
| Hybrid | `BD 40 08 0B 0F 00 04 14` |
| Heat Pump | `BD 40 08 0B 0F 00 05 4A` |
| Electric, one day | `BD 40 08 0B 0F 01 01 FE` |
| Vacation, one day | `BD 40 08 0B 0F 01 02 1C` |

Final byte is the checksum field described by prior research; a general checksum
implementation has not yet been verified here. Duration encoding inferred from
these captures still needs more values before generalizing.

`superBlockDyn1` contains five comma-separated hex blocks with byte lengths
8, 148, 230, 52, 52. Block index 3, byte offsets 0 and 12, independently matched
129°F and 130°F: unsigned big-endian 16-bit Celsius /256. Mode bytes at offsets
30–31 match the selected modes. Vacation temporarily reports 50°F; returning
to Hybrid restores the original 130°F target.

Cloud API mode pending flags cleared for all four modes. These checks establish
reported controller state, not full thermal performance in each mode.

## Next work

Build an offline emulator from sanitized fixtures; validate bootstrap,
periodic settings, command delivery/acknowledgement, telemetry, reconnection,
clock and UDP notification dependencies. Then conduct a reviewed bounded live
trial. Current relay still requires the cloud. Home Assistant integration,
installation packaging, and Internet isolation are not yet implemented.

Use `decode_http.py` to decode private captures and `summarize_capture.py` for
selected readings. The former writes sensitive headers; keep output private.
Before public release, inspect all files and Git history for credentials and
household identifiers, attribute reused work, and check upstream licensing.
