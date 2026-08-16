#!/bin/bash
# Por qué no se llega a Cloudflare R2. Solo lee, no cambia nada.

HOST="${R2_ACCOUNT_ID:-baf85529148a880be8ce4b0144538c5d}.r2.cloudflarestorage.com"
PUB="pub-3ae46c42906e460bbeee92a4cf1c3b76.r2.dev"

echo "=== 1. DNS ==="
for h in "$HOST" "$PUB" cloudflare.com; do
  printf '%-60s %s\n' "$h" "$(dig +short +time=3 +tries=1 "$h" A | head -2 | tr '\n' ' ')"
done

echo
echo "=== 2. HTTPS (10 s de límite) ==="
for h in "$HOST" "$PUB" cloudflare.com graph.facebook.com; do
  printf '%-60s ' "$h"
  curl -s -o /dev/null -w 'http=%{http_code} conexion=%{time_connect}s total=%{time_total}s\n' \
    --max-time 10 "https://$h/" || echo "sin conexion"
done

echo
echo "=== 3. Forzando IPv4 ==="
printf '%-60s ' "$HOST (IPv4)"
curl -4 -s -o /dev/null -w 'http=%{http_code} total=%{time_total}s\n' \
  --max-time 10 "https://$HOST/" || echo "sin conexion"

echo
echo "=== 4. Puerto 443 ==="
nc -vz -w 5 "$HOST" 443 2>&1 | tail -2

echo
echo "=== 5. Servidores DNS en uso ==="
scutil --dns 2>/dev/null | grep nameserver | sort -u | head -5

echo
echo "=== 6. Interfaces de VPN levantadas ==="
ifconfig 2>/dev/null | grep -E '^(utun|ipsec|tun|ppp)[0-9]*:' | cut -d: -f1 | tr '\n' ' '
echo

echo
echo "=== 7. Proxy configurado en el sistema ==="
scutil --proxy 2>/dev/null | grep -iE 'enable|proxy' | head -8
