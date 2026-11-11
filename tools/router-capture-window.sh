#!/bin/sh
# Run on the gateway only after reviewing the owner-specific endpoint values.
# Per-window tags prevent an expired watchdog from deleting a later trial.
set -eu
: "${HEATER:?}" "${HTTPS_UPSTREAM:?}" "${UDP_UPSTREAM:?}" "${TARGET:?}" "${GATEWAY:?}" "${RUN_ID:?}"
for value in "$HEATER" "$HTTPS_UPSTREAM" "$UDP_UPSTREAM" "$TARGET" "$GATEWAY"; do
    case "$value" in ''|*[!0-9.]*) exit 2;; esac
done
case "$RUN_ID" in ''|*[!a-zA-Z0-9_-]*) exit 2;; esac
TAG="icomm-capture-$RUN_ID"
ENABLE_UDP_FORWARD=${ENABLE_UDP_FORWARD:-0}
case "$ENABLE_UDP_FORWARD" in 0|1) ;; *) exit 2;; esac
cleanup() {
    removed=0
    if iptables -t nat -D PREROUTING -s "$HEATER" -d "$HTTPS_UPSTREAM" -p tcp --dport 443 -m comment --comment "$TAG" -j DNAT --to-destination "$TARGET:8444" 2>/dev/null; then removed=1; fi
    if iptables -t nat -D PREROUTING -s "$HEATER" -d "$UDP_UPSTREAM" -p udp --dport 55055:55056 -m comment --comment "$TAG" -j DNAT --to-destination "$TARGET" 2>/dev/null; then removed=1; fi
    if iptables -t nat -D POSTROUTING -s "$HEATER" -d "$TARGET" -p tcp --dport 8444 -m comment --comment "$TAG" -j SNAT --to-source "$GATEWAY" 2>/dev/null; then removed=1; fi
    if iptables -t nat -D POSTROUTING -s "$HEATER" -d "$TARGET" -p udp --dport 55055:55056 -m comment --comment "$TAG" -j SNAT --to-source "$GATEWAY" 2>/dev/null; then removed=1; fi
    if [ "$removed" = 1 ]; then
        conntrack -D -s "$HEATER" -d "$HTTPS_UPSTREAM" -p tcp --dport 443 >/dev/null 2>&1 || true
        if [ "$ENABLE_UDP_FORWARD" = 1 ]; then
            conntrack -D -s "$HEATER" -d "$UDP_UPSTREAM" -p udp --dport 55055 >/dev/null 2>&1 || true
            conntrack -D -s "$HEATER" -d "$UDP_UPSTREAM" -p udp --dport 55056 >/dev/null 2>&1 || true
        fi
    fi
    echo "ROLLBACK COMPLETE $TAG $(date -u)"
}
if [ "${1:-}" = cleanup ]; then cleanup; exit 0; fi
[ "${1:-}" = start ] || exit 2
case "${WINDOW_SECONDS:-240}" in ''|*[!0-9]*) exit 2;; esac
[ "${WINDOW_SECONDS:-240}" -ge 10 ] && [ "${WINDOW_SECONDS:-240}" -le 240 ]
if iptables -t nat -S PREROUTING | grep -q 'icomm-capture-'; then echo 'Another capture window exists'; exit 1; fi
trap cleanup EXIT
trap 'exit 0' HUP INT TERM
iptables -t nat -I POSTROUTING 1 -s "$HEATER" -d "$TARGET" -p tcp --dport 8444 -m comment --comment "$TAG" -j SNAT --to-source "$GATEWAY"
if [ "$ENABLE_UDP_FORWARD" = 1 ]; then
iptables -t nat -I POSTROUTING 1 -s "$HEATER" -d "$TARGET" -p udp --dport 55055:55056 -m comment --comment "$TAG" -j SNAT --to-source "$GATEWAY"
fi
iptables -t nat -I PREROUTING 1 -s "$HEATER" -d "$HTTPS_UPSTREAM" -p tcp --dport 443 -m comment --comment "$TAG" -j DNAT --to-destination "$TARGET:8444"
if [ "$ENABLE_UDP_FORWARD" = 1 ]; then
iptables -t nat -I PREROUTING 1 -s "$HEATER" -d "$UDP_UPSTREAM" -p udp --dport 55055:55056 -m comment --comment "$TAG" -j DNAT --to-destination "$TARGET"
fi
conntrack -D -s "$HEATER" -d "$HTTPS_UPSTREAM" -p tcp --dport 443 >/dev/null 2>&1 || true
if [ "$ENABLE_UDP_FORWARD" = 1 ]; then
conntrack -D -s "$HEATER" -d "$UDP_UPSTREAM" -p udp --dport 55055 >/dev/null 2>&1 || true
fi
if [ "$ENABLE_UDP_FORWARD" = 1 ]; then
conntrack -D -s "$HEATER" -d "$UDP_UPSTREAM" -p udp --dport 55056 >/dev/null 2>&1 || true
fi
echo "CAPTURE WINDOW ACTIVE $TAG $(date -u)"
sleep "${WINDOW_SECONDS:-240}"
