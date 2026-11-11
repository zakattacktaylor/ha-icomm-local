# iCOMM development capture harness

This add-on currently records/forwards traffic. It is **not yet a cloud emulator
or a working local-control integration**. See the repository's implementation
plan and [capture procedure](../../docs/development-capture.md).

Configure a random management token of at least 24 characters and the exact
allowed source IPv4 addresses. Start the add-on manually. Only the authenticated
management API is active until a capture starts. Never expose its ports to the
Internet. Raw captures contain appliance authentication data and identifiers.
