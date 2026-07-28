#!/usr/bin/env bash
set -Eeuo pipefail

NAMESPACE="${NAMESPACE:-ticket-system}"
GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:8000}"
EVENT_ID="${EVENT_ID:-3}"
USER_A="${USER_A:-9301}"
USER_B="${USER_B:-9302}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "=== CONDICIÓN DE CARRERA / K3s ==="

echo
 echo "[ANTES] Preparando exactamente un asiento para el evento $EVENT_ID ..."
kubectl exec -n "$NAMESPACE" deployment/postgres -- \
  psql -U ticket_user -d ticket_db \
  -c "UPDATE inventory SET available=1,updated_at=CURRENT_TIMESTAMP WHERE event_id=$EVENT_ID; SELECT event_id,available FROM inventory WHERE event_id=$EVENT_ID;"

# Evita que un rate-limit residual de otra prueba contamine la carrera.
echo
echo "Esperando 11 s para limpiar la ventana de rate limiting ..."
sleep 11

echo
echo "[FALLO] Lanzando dos reservas simultáneas por el último asiento ..."

curl -sS -o "$TMP_DIR/a.json" -w '%{http_code}' \
  -X POST "$GATEWAY_URL/api/reservations" \
  -H 'Content-Type: application/json' \
  -d "{\"event_id\":$EVENT_ID,\"user_id\":$USER_A,\"quantity\":1}" \
  > "$TMP_DIR/a.code" &
PID_A=$!

curl -sS -o "$TMP_DIR/b.json" -w '%{http_code}' \
  -X POST "$GATEWAY_URL/api/reservations" \
  -H 'Content-Type: application/json' \
  -d "{\"event_id\":$EVENT_ID,\"user_id\":$USER_B,\"quantity\":1}" \
  > "$TMP_DIR/b.code" &
PID_B=$!

wait "$PID_A"
wait "$PID_B"

CODE_A="$(cat "$TMP_DIR/a.code")"
CODE_B="$(cat "$TMP_DIR/b.code")"

echo
echo "===== USUARIO $USER_A ====="
echo "HTTP $CODE_A"
python3 -m json.tool < "$TMP_DIR/a.json" || cat "$TMP_DIR/a.json"

echo
echo "===== USUARIO $USER_B ====="
echo "HTTP $CODE_B"
python3 -m json.tool < "$TMP_DIR/b.json" || cat "$TMP_DIR/b.json"

python3 - "$CODE_A" "$CODE_B" <<'PY'
import sys

codes = sorted([sys.argv[1], sys.argv[2]])
if codes != ["200", "409"]:
    raise SystemExit(f"ERROR: se esperaba exactamente un HTTP 200 y un HTTP 409; se obtuvo {codes}")
PY

echo
echo "[EVIDENCIA] Estado final de inventario y reservas:"
kubectl exec -n "$NAMESPACE" deployment/postgres -- \
  psql -U ticket_user -d ticket_db \
  -c "SELECT event_id,available FROM inventory WHERE event_id=$EVENT_ID; SELECT user_id,event_id,quantity,status FROM reservations WHERE event_id=$EVENT_ID AND user_id IN ($USER_A,$USER_B) ORDER BY created_at DESC;"

AVAILABLE="$(kubectl exec -n "$NAMESPACE" deployment/postgres -- \
  psql -U ticket_user -d ticket_db -Atc "SELECT available FROM inventory WHERE event_id=$EVENT_ID;")"

SUCCESS_COUNT="$(kubectl exec -n "$NAMESPACE" deployment/postgres -- \
  psql -U ticket_user -d ticket_db -Atc "SELECT COUNT(*) FROM reservations WHERE event_id=$EVENT_ID AND user_id IN ($USER_A,$USER_B) AND status='CONFIRMED';")"

if [[ "$AVAILABLE" != "0" ]]; then
  echo "ERROR: inventario final esperado=0; obtenido=$AVAILABLE" >&2
  exit 1
fi

if [[ "$SUCCESS_COUNT" != "1" ]]; then
  echo "ERROR: se esperaba una sola reserva CONFIRMED; obtenidas=$SUCCESS_COUNT" >&2
  exit 1
fi

echo
echo "=== RESULTADO COMPROBADO ==="
echo "Un usuario ganó: HTTP 200"
echo "Un usuario perdió: HTTP 409"
echo "Inventario final: 0"
echo "Reservas CONFIRMED de la carrera: 1"
