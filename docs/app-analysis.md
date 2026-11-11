# iCOMM Android metadata investigation

Static inspection completed November 11, 2026. No app code was installed or
executed, no account credentials were supplied to the downloaded package, and
no heater settings were changed.

## Artifact identification

- Package: `com.aosmith.icomm`
- Version: `14.1.0`, version code `50000114`
- XAPK SHA-256:
  `60c4754f0bc1740541d7ab470c25c9d166ec7bc9ac26c2815b66ab8c50ae9a37`
- Base APK SHA-256:
  `18cb2b977c049a9c4b4cf38a92dd0ce7fc57dc42b9b51f63fee17bd009992c7e`
- Android APK signature verification succeeded. Signing certificate SHA-256:
  `817908c7efb7f780f78380ade57049978eacf2213dead0a6ccd56e3cfd771a40`
- Obtained from APKPure's public XAPK download. The archive checksum matched
  that mirror's published value. This does not by itself establish publisher
  provenance; Android signature metadata and the package/version were also
  recorded for reproducibility.

The app is React Native with a Hermes bytecode version 96 bundle of 5,407,404
bytes. Disassembled offline using P1sec/hermes-dec 0.1.8. APKs, bytecode, strings,
and disassembly are retained outside this repository, not redistributed here.

## `updateMetadata` call site

The actionable result is that the identified application-level call site uses:

- Function: `updateRatePlanMetadata`
- GraphQL operation: `updateMetadata`
- Device argument: DSN
- Metadata key: **`timeOfUse`**
- Metadata value: a JSON-encoded rate-plan object, with its type marked `manual`
  when seasonal data is present, otherwise `auto`.

Equivalent request-variable structure, with synthetic placeholders:

```json
{
  "dsn": "<device-dsn>",
  "data": {
    "key": "timeOfUse",
    "value": "<JSON-encoded rate-plan object>"
  }
}
```

The rate-plan deletion path calls `deleteMetadata` with the same `timeOfUse`
key. This is evidence that this metadata use manages tariff/rate-plan
information. It provides no evidence that arbitrary metadata keys enable LAN
control or configure the module's LAN key.

## Reference tracing

The Hermes disassembly's `UPDATE_METADATA` references were:

- Function 14991: actual GraphQL invocation, nested under
  `updateRatePlanMetadata` (14988); key loaded from the literal `timeOfUse`.
- Function 15041: operation-name and query registry wiring.

The mutation text occurs separately in function 15137. A Firebase Storage
`updateMetadata()` symbol elsewhere is unrelated to the heater GraphQL API.
These function numbers identify this exact bundle and can change between builds.

## Search for other LAN configuration

The app's operation registry contains 41 named operations, including settings
for mode, setpoint, temperature differential, alerts, leak detection, schedules,
utility enrollment and metadata. It contains no explicit LAN-enable, LAN-key,
or LAN-configuration operation. An additional `IntrospectionQuery` string is
present in the client library; the live server still rejects introspection.

No `lanip`, `local_reg`, `lan_enabled`, `local_access_enabled`, or
`connection_priority` literal was found in the Hermes disassembly. None of
`aylanetworks`, `lanip`, or `local_reg` appeared in the six extracted DEX files.
The superficially matching `getLan`/`setLan` symbols resolve to language methods,
not LAN networking.

The app does contain a Wi-Fi provisioning path using the hotspot base address
`http://192.168.0.1` and `/wifi_status.json` and `/wifi_connect.json?` routes.
That address is for the heater's own temporary hotspot, not necessarily its
address on an established home network.

## Conclusion and limits

The metadata lead is explained by the app's time-of-use feature. This version's
visible operation map and checked code do not reveal a hidden LAN-control
setting. Static string/reference analysis cannot prove the backend has no
additional undocumented operation or key interpreted server-side. In particular,
this was not a blind write test of arbitrary metadata names.

The remaining distinct research paths are the Ayla cloud-protocol emulator and
its notification channel, or the separately gated LAN provisioning mechanism.
