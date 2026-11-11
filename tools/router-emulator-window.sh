#!/bin/sh
# Single heater; bounded trial only. Never flushes a firewall table.
set -eu
: "${HEATER:?}" "${HEATER_MAC:?}" "${TARGET:?}" "${GATEWAY:?}" "${RUN_ID:?}"
WINDOW_SECONDS=${WINDOW_SECONDS:-240}
case "$HEATER$TARGET$GATEWAY" in *[!0-9.]*) exit 2;; esac
case "$HEATER_MAC" in *[!0-9a-fA-F:]*|'') exit 2;; esac
case "$RUN_ID" in *[!a-zA-Z0-9_-]*|'') exit 2;; esac
case "$WINDOW_SECONDS" in *[!0-9]*|'') exit 2;; esac
[ "$WINDOW_SECONDS" -ge 10 ] && [ "$WINDOW_SECONDS" -le 900 ] || exit 2
TAG="icomm-offline-$RUN_ID"
rule() {
 op=$1; shift
 case "$1" in
 http-in) iptables -t nat "$op" PREROUTING -s "$HEATER" -p tcp --dport 80 -m comment --comment "$TAG" -j DNAT --to-destination "$TARGET:8788";;
 http-out) iptables -t nat "$op" POSTROUTING -s "$HEATER" -d "$TARGET" -p tcp --dport 8788 -m comment --comment "$TAG" -j SNAT --to-source "$GATEWAY";;
 https-in) iptables -t nat "$op" PREROUTING -s "$HEATER" -p tcp --dport 443 -m comment --comment "$TAG" -j DNAT --to-destination "$TARGET:8444";;
 https-out) iptables -t nat "$op" POSTROUTING -s "$HEATER" -d "$TARGET" -p tcp --dport 8444 -m comment --comment "$TAG" -j SNAT --to-source "$GATEWAY";;
 udp-in) iptables -t nat "$op" PREROUTING -s "$HEATER" -p udp --dport 55055:55056 -m comment --comment "$TAG" -j DNAT --to-destination "$TARGET";;
 udp-out) iptables -t nat "$op" POSTROUTING -s "$HEATER" -d "$TARGET" -p udp --dport 55055:55056 -m comment --comment "$TAG" -j SNAT --to-source "$GATEWAY";;
 wan4) iptables "$op" FORWARD -s "$HEATER" ! -d 192.168.0.0/24 -m comment --comment "$TAG" -j REJECT;;
 wan6) ip6tables "$op" FORWARD -m mac --mac-source "$HEATER_MAC" -m comment --comment "$TAG" -j REJECT;;
 esac
}
expire() {
 for port in 80 443; do conntrack -D -s "$HEATER" -p tcp --dport "$port" >/dev/null 2>&1 || true; done
 for port in 55055 55056; do conntrack -D -s "$HEATER" -p udp --dport "$port" >/dev/null 2>&1 || true; done
}
cleanup() {
 changed=0
 for name in wan4 wan6 http-in http-out https-in https-out udp-in udp-out; do
  if rule -D "$name" >/dev/null 2>&1; then changed=1; fi
 done
 if [ "$changed" = 1 ]; then expire; fi
 echo "ROLLBACK COMPLETE $TAG $(date -u)"
}
case "${1:-}" in
 cleanup) cleanup;;
 start)
  if iptables -t nat -S PREROUTING | grep -q 'icomm-\(capture\|offline\)-'; then echo 'Existing trial window'; exit 1; fi
  # Preflight IPv6 support before any change. This is an IPv4 local service.
  ip6tables -S FORWARD >/dev/null
  trap cleanup EXIT HUP INT TERM
  rule -I http-out
  rule -I https-out
  rule -I udp-out
  rule -I http-in
  rule -I https-in
  rule -I udp-in
  rule -I wan4
  rule -I wan6
  expire
  echo "OFFLINE WINDOW ACTIVE $TAG $(date -u)"
  sleep "$WINDOW_SECONDS"
 ;;
 *) exit 2;;
esac
