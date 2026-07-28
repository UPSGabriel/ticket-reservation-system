#!/usr/bin/env bash
set -Eeuo pipefail

NAMESPACE="${NAMESPACE:-ticket-system}"
GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:8000}"
EVENT_ID="${EVENT_ID:-1}"
BASE_USER_ID="${BASE_USER_ID:-9200}"
BEFORE_USER=$((BASE_USER_ID + 1))
SLOW_USER=$((BASE_USER_ID + 2))
AFTER_USER=$((BASE_USER_ID + 3))

TMP_DIR="$(mktemp -d)"
RESTORED=0

get_env() {
  local deployment="$1"
  local variable="$2"
  kubectl get deployment "$deployment" -n "$NAMESPACE" \
    -o jsonpath="{.spec.template.spec.containers[0].env[?(@.name==\"$variable\")].value}"
}

PAYMENT_DELAY_ORIGINAL="$(get_env payment-service PAYMENT_DELAY_SECONDS)"
PAYMENT_MODE_ORIGINAL="$(get_env payment-service PAYMENT_FAILURE_MODE)"
PAYMENT_RATE_ORIGINAL="$(get_env payment-service PAYMENT_FAILURE_RATE)"
NOTIFICATION_MODE_ORIGINAL="$(get_env notification-service NOTIFICATION_FAILURE_MODE)"
NOTIFICATION_RATE_ORIGINAL="$(get_env notification-service NOTIFICATION_FAILURE_RATE)"

wait_payment_ready() {
  local attempt
  for attempt in $(seq 1 30); do
    if kubectl exec -n "$NAMESPACE" deployment/reservation-service -- \
      python -c 'import sys, urllib.request; r=urllib.request.urlopen(sys.argv[1], timeout=3); print(r.read().decode())' \
      'http://payment-service:8003/health' >/tmp/payment-health.out 2>/tmp/payment-health.err; then
      cat /tmp/payment-health.out
      return 0
    fi
    echo "Payment aún no responde (intento $attempt/30). Reintentando en 2 s ..."
    sleep 2
  done
  echo "ERROR: Payment no quedó accesible a través del Service." >&2
  cat /tmp/payment-health.err >&2 || true
  return 1
}

restore_original_config() {
  if [[ "$RESTORED" -eq 1 ]]; then
    return
  fi

  echo
  echo "[LIMPIEZA] Restaurando configuración original ..."
  kubectl set env deployment/payment-service -n "$NAMESPACE" \
    PAYMENT_DELAY_SECONDS="$PAYMENT_DELAY_ORIGINAL" \
    PAYMENT_FAILURE_MODE="$PAYMENT_MODE_ORIGINAL" \
    PAYMENT_FAILURE_RATE="$PAYMENT_RATE_ORIGINAL" >/dev/null

  kubectl set env deployment/notification-service -n "$NAMESPACE" \
    NOTIFICATION_FAILURE_MODE="$NOTIFICATION_MODE_ORIGINAL" \
    NOTIFICATION_FAILURE_RATE="$NOTIFICATION_RATE_ORIGINAL" >/dev/null

  kubectl rollout status deployment/payment-service -n "$NAMESPACE" --timeout=240s
  kubectl rollout status deployment/notification-service -n "$NAMESPACE" --timeout=240s
  RESTORED=1
}

cleanup() {
  restore_original_config || true
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

send_reservation() {
  local user_id="$1"
  local output="$2"
  local code

  code="$(curl -sS -o "$output" -w '%{http_code}' \
    -X POST "$GATEWAY_URL/api/reservations" \
    -H 'Content-Type: application/json' \
    -d "{\"event_id\":$EVENT_ID,\"user_id\":$user_id,\"quantity\":1}")"

  echo "HTTP $code"
  python3 -m json.tool < "$output" || cat "$output"
  echo "$code"
}

assert_status() {
  local file="$1"
  local expected="$2"
  python3 - "$file" "$expected" <<'PY'
import json
import sys

path, expected = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)
actual = data.get("status")
if actual != expected:
    raise SystemExit(f"ERROR: se esperaba status={expected}; se obtuvo {actual}")
PY
}

echo "=== PASARELA LENTA / K3s ==="

echo
 echo "[ESTABILIZACIÓN] Desactivando fallos aleatorios para una demo determinista ..."
kubectl set env deployment/payment-service -n "$NAMESPACE" \
  PAYMENT_DELAY_SECONDS=0 PAYMENT_FAILURE_MODE=none PAYMENT_FAILURE_RATE=0
kubectl set env deployment/notification-service -n "$NAMESPACE" \
  NOTIFICATION_FAILURE_MODE=none NOTIFICATION_FAILURE_RATE=0
kubectl rollout status deployment/payment-service -n "$NAMESPACE" --timeout=240s
kubectl rollout status deployment/notification-service -n "$NAMESPACE" --timeout=240s
wait_payment_ready

echo
 echo "[ANTES] Reserva normal:"
send_reservation "$BEFORE_USER" "$TMP_DIR/before.json" >/tmp/pasarela-before.out
cat /tmp/pasarela-before.out
assert_status "$TMP_DIR/before.json" CONFIRMED

echo
 echo "[FALLO] Inyectando 20 s de latencia fija en Payment ..."
kubectl set env deployment/payment-service -n "$NAMESPACE" \
  PAYMENT_DELAY_SECONDS=20 PAYMENT_FAILURE_MODE=none PAYMENT_FAILURE_RATE=0
kubectl rollout status deployment/payment-service -n "$NAMESPACE" --timeout=240s
wait_payment_ready

echo "PAYMENT_DELAY_SECONDS=$(get_env payment-service PAYMENT_DELAY_SECONDS)"

echo
 echo "[DURANTE] Reserva con Payment lento:"
send_reservation "$SLOW_USER" "$TMP_DIR/slow.json" >/tmp/pasarela-slow.out
cat /tmp/pasarela-slow.out
assert_status "$TMP_DIR/slow.json" PAYMENT_PENDING

echo
 echo "[EVIDENCIA] Logs de Reservation:"
kubectl logs -n "$NAMESPACE" -l app=reservation-service --since=10m \
  --prefix=true --max-log-requests=10 \
  | grep -E 'Servicio de Pagos|PAYMENT_PENDING|Reserva' || true

echo
 echo "[EVIDENCIA] Persistencia en PostgreSQL:"
kubectl exec -n "$NAMESPACE" deployment/postgres -- \
  psql -U ticket_user -d ticket_db \
  -c "SELECT id,user_id,status,payment_status,notification_status FROM reservations WHERE user_id=$SLOW_USER ORDER BY created_at DESC LIMIT 1;"

echo
 echo "Esperando a que el pago lento complete su ejecución para capturar su log ..."
sleep 18
kubectl logs -n "$NAMESPACE" -l app=payment-service --since=10m \
  --prefix=true --max-log-requests=10 \
  | grep -E 'esperara 20\.000|resultado=APPROVED' || true

echo
 echo "[RECUPERACIÓN] Restaurando Payment sin latencia ..."
kubectl set env deployment/payment-service -n "$NAMESPACE" \
  PAYMENT_DELAY_SECONDS=0 PAYMENT_FAILURE_MODE=none PAYMENT_FAILURE_RATE=0
kubectl rollout status deployment/payment-service -n "$NAMESPACE" --timeout=240s
wait_payment_ready

echo
 echo "[DESPUÉS] Nueva reserva normal:"
send_reservation "$AFTER_USER" "$TMP_DIR/after.json" >/tmp/pasarela-after.out
cat /tmp/pasarela-after.out
assert_status "$TMP_DIR/after.json" CONFIRMED

echo
 echo "=== RESULTADO COMPROBADO ==="
echo "Antes: CONFIRMED"
echo "Durante: PAYMENT_PENDING con inventario reservado y fila persistida"
echo "Después: CONFIRMED"

restore_original_config
trap - EXIT
rm -rf "$TMP_DIR"
