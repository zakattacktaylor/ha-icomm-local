# HTTP server observations

Read-only exploration of one HPTS-80 with iCOMM NextGenHP, November 11, 2026.
85 requests tested route names, HEAD/OPTIONS, HTTP versions, Host behavior, and
simple path normalization, with periodic health checks. This is not exhaustive
firmware fuzzing and does not establish the behavior of every iCOMM generation.

## Reachable in normal connected Wi-Fi mode

| Path | GET response | Purpose |
|---|---|---|
| `/client` | 200, HTML, 721 bytes | Browser page displaying the device registration code |
| `/regtoken.json` | 200, JSON | Registration token/status and symbolic device family |
| `/style.css` | 200, CSS, 3889 bytes | Embedded UI stylesheet |
| `/lock.gif` | 200, GIF, 148 bytes | Embedded UI image |
| `/refresh.gif` | 200, GIF, 158 bytes | Embedded UI image |

The `/client` response matched this archived agent resource byte for byte:
https://github.com/ddkity/Roomba1.4.3/blob/master/component/common/ayla/libada/text/regtoken.html.txt

That is evidence of shared resource/code lineage, not proof that the entire
firmware, build options, or access-control behavior matches the archive.
The page reads `regtoken.json` with JavaScript and displays the code. It contains
no controls, configuration form, links to administration, or additional APIs.
Registration codes and actual raw responses are deliberately excluded here.

## HTTP behavior

- HEAD works on the tested GET resources, with an empty body.
- OPTIONS closed the connection without an HTTP response on both known and
  nonexistent routes; it did not advertise supported methods.
- HTTP/1.0 and HTTP/1.1 without Host both reached `regtoken.json`.
- Plain numeric Host worked; numeric Host with `:80`, `localhost`, or the OEM
  cloud hostname produced generic HTML 404 even for the known-valid route.
- Query strings were accepted on `regtoken.json`.
- Trailing slash, changed case, percent-encoded characters, dot segments, and a
  doubled leading slash did not normalize to the known route.
- Browser versus mobile User-Agent and Accept headers did not change the result.
- The observed replies did not advertise a Server software/version banner.

## Routes not exposed by the tested normal-LAN requests

These returned generic HTML 404, including a follow-up without Host where noted:

- `/status.json`, `/time.json`, `/config.json`
- `/property.json`, including `?name=superBlockDyn1`, `/properties.json`
- `/wifi`, `/wifi.js`, `/wifi_status.json`, `/wifi_profiles.json`,
  `/wifi_scan_results.json`
- `/lanip.json`, `/lan.json`
- Guessed information/configuration paths such as `/client.json`, `/setup`,
  `/config`, `/settings`, `/service`, and their tested variants.

Separately, prior owner-authorized LAN-only configuration attempts found that
POST/PUT `/local_reg.json` returned **empty 404**, while its GET returned the
161-byte HTML 404. The related agent's registration handler explicitly returns
404 when LAN access is disabled, consistent with this observation. Empty 404
alone is not conclusive proof of which internal check failed.

## Access classes in the related agent

The source selects handlers using method, exact path, and internal request
privileges. It distinguishes ordinary local HTTP, setup/AP-mode requests,
registered app requests, and reverse-REST requests delivered through the cloud.
A different HTTP Host header does not grant cloud privileges.

The archived source labels `PUT /lanip.json` as a cloud/reverse-REST operation.
Its Wi-Fi setup pages and several information routes are gated to setup mode or
registered app/cloud access. It also contains legacy service configuration
functions for cloud hostname/poll interval, but those functions were not found
reachable in our normal-LAN inventory. Their presence in source is not evidence
that they can be invoked on this heater.

No reset, firmware, Wi-Fi configuration, or heating-control writes were made
during this read-only exploration. Normal registration GET checks continued to
succeed. Exploring the separate temporary setup-mode surface remains untested;
that requires coordinating the physical Wi-Fi pairing button and may interrupt
the network connection. It should not be confused with a factory reset.
