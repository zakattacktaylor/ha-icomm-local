# Cloud API discovery

Authenticated exploration of the iCOMM GraphQL service, November 11, 2026.
This report contains no account/device identifiers, tokens, or raw responses.
No heater-control or configuration mutation was executed during this research.

## Verified behavior

- The app-facing endpoint is `https://r2.wh8.co/graphql`.
- Normal login and the existing full-device query worked.
- `__schema` and `__type` introspection explicitly return HTTP 400: Apollo
  production introspection is disabled. Therefore this is not a complete schema
  inventory, and failure to find a guessed field does not prove no alternative
  operation exists.
- `__typename` is allowed. Relevant types include `Device`, `NextGenHeatPump`,
  `Hardware`, `User`, and `TokenSet`.
- The known full-device response exposes status, modes, schedules, alarms,
  demand-response fields, firmware version, and Wi-Fi/Bluetooth hardware metadata.
  That query returned no LAN key/enable/configuration data.

## LAN-specific candidates rejected by schema validation

The tested fields `lanEnabled`, `lanSupport`, `lanConfig`, `lanip`, `lanipKey`,
`connectionPriority`, and `localAccessEnabled` were not defined on Device or
NextGenHeatPump. Tested snake-case variants were likewise absent on Device.
The tested LAN/network/settings fields on Hardware were absent.

Root query names such as `getLanConfig`, `getLanKey`, `getDeviceLanConfig`,
`deviceSettings`, `deviceConfiguration`, and `getDeviceCredentials` were not
recognized. Root mutation names such as `enableLan`, `updateLanConfig`,
`updateLanSettings`, `setLanMode`, `enableLocalAccess`, `updateConnectivity`,
`sendCommand`, and `updateProperty` were not recognized.

These are targeted negative results, not exhaustive enumeration.

## Broader operations recognized by validation

| Operation | Discovered required input |
|---|---|
| `updateDeviceDetails` | `junctionId: String!`, `details: HeaterProfileInputType!` |
| `updateMetadata` | `dsn: String!`, `data: MetadataInput!` |
| `registerDevice` | `serial: String!`, `name: String!`, `location: String!` |
| `updateUserPermissions` | `contactId: String!`, `junctionId: String!`, `permissions: DevicePermission!` |
| `updateLeakDetection` | `junctionId: String!` |

Recognition establishes schema membership, not authorization or successful
operation for a particular account/device. None of these mutations was executed.

`HeaterProfileInputType` rejected the tested LAN fields. `MetadataInput` requires
string `key` and `value` fields. The shape
`updateMetadata(dsn: ..., data: {key: ..., value: ...})` passed argument/type
validation; an additional intentionally invalid root field prevented execution.

**The metadata operation is an unresolved lead.** It might store application
annotations or values interpreted by the backend. A generic key/value input is
not evidence that a key such as `lan_enabled` actually configures the module.
No metadata key was written, and no tested getter exposed existing metadata.
The next useful evidence would be the app's actual metadata keys and call sites.

## Discovery method

For mutation name/input validation, every request also contained a deliberately
undefined root field. GraphQL rejected the operation during validation before
resolver execution. Read queries used `forceUpdate: false` to avoid requesting
extra device communication. Secret-bearing login/device/error responses were
stored privately outside this repository. Common public OpenAPI/Swagger/SDL/UI
paths on the same service returned 404.

Ayla documents LAN support separately as a template/device setting:
https://docs.aylanetworks.com/docs/templates#lan-mode

This does not establish whether A. O. Smith exposes that setting through an
unidentified app-facing operation. An app APK mirror download attempt returned
403; no app binary was downloaded or executed in this investigation.

## Subsequent app inspection

The app's actual metadata call site has now been traced to the key `timeOfUse`,
used for rate-plan storage/deletion. No LAN-enable use was identified. See
[the static app investigation](app-analysis.md) for version, hashes, evidence,
and limits. This resolves the app-side metadata lead without writing guesses
to the heater or account.
