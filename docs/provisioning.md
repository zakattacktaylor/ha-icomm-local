# Provisioning status and operator checklist

This procedure is experimental. It has not yet successfully provisioned the
development HPTS-80. Do not present it as a verified installation guide.

The LAN server itself does not contact the cloud. A one-time TLS proxy is used
to deliver the vendor device agent's `PUT lanip.json` reverse-REST operation,
which saves a LAN key. Prior research demonstrated this mechanism on another
NextGen heater. Our heater has not yet fetched the queued configuration command.

## Preparation

1. Back up Home Assistant and record the normal heater target and mode.
2. Generate a random ASCII LAN key (32 hex characters), with key ID 1. Keep a
   JSON file containing `key` and `key_id` outside this Git repository, mode 0600.
   Preserve it in a secure backup; removing the integration does not erase it.
3. Install the custom component and configure the heater address, HA callback
   address, LAN key/key ID, and callback TCP port. Before provisioning, local
   registration may return HTTP 404 and the entity remains unavailable.
4. Prepare a private RSA/SHA256 TLS certificate/key and 2048-bit DH parameters
   for the provisioning proxy. The observed firmware accepts TLS 1.2 using
   DHE-RSA-AES256-SHA. This legacy setting is limited to the temporary proxy.
5. Arrange a narrowly scoped, temporary redirect for this heater's HTTPS traffic
   to its observed Ayla server. Use an independent on-router expiry and rollback.
   Do not change global DNS or route other devices through the proxy.

## Bounded proxy

`tools/provision_proxy.py` accepts file paths and nonsecret network settings:

```sh
python tools/provision_proxy.py --lan-config /private/path/lan.json \
  --bind PROXY_LAN_IP --allowed-peer ROUTER_OR_HEATER_IP \
  --cert /private/path/cert.pem --key /private/path/key.pem \
  --dh-params /private/path/dh.pem --seconds 300
```

The proxy never installs routes itself. It forwards the original OEM HTTP Host
header unchanged and verifies the upstream TLS certificate/hostname. A separately
verified legacy CA may be supplied with `--upstream-ca` when necessary; do not
turn off upstream verification or globally alter the system trust store.

On the next successful `commands.xml` poll it inserts only a LAN-key configuration
command, preserving existing properties and declining to displace any existing
reverse-REST command. The acknowledgement should report status 204. It can also
serve `/devices/<id>/lan.json` if requested after enabling LAN flags in a fresh
identity snapshot. It does not generate mode, temperature, reset, or firmware
commands. Console logs omit credentials and key material.

## Required validation before calling this complete

- Receive a valid key exchange and authenticated local telemetry from the heater.
- Issue a bounded local command and confirm it in fresh telemetry, then restore
  the normal target/mode. An acknowledgement alone is not confirmation.
- Remove temporary routing and stop the proxy. Verify local operations continue.
- Temporarily deny only the heater's Internet access, retaining HA/LAN access;
  verify commands and fresh telemetry still work, then restore the network policy.
- Check heater/network restart and HA restart recovery before permanent isolation.

During development, incorrect HTTP forwarding and authentication experiments
were followed by cloud control failures and long device retry delays. A Wi-Fi
reassociation did not immediately clear that state. Do not repeatedly issue
commands or reset pairing to force it. Preserve the key and allow recovery or
coordinate an ordinary power cycle. Never factory-reset or change mains wiring
as part of this procedure.
