#!/usr/bin/env bash
set -Eeuo pipefail

NAMESPACE="${NAMESPACE:-ticket-system}"
TARGET_NODE="${TARGET_NODE:-gabriel-node}"
GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:8000}"
EVENT_ID="${EVENT_ID:-1}"
USER_ID="${USER_ID:-9102}"
QUANTITY="${QUANTITY:-1}"

TMP_RESPONSE="$(mktemp)"
trap 'rm -f "$TMP_RESPONSE"' EXIT

echo "=== INVENTARIO FANTASMA / K3s ==="
echo "Namespace: $NAMESPACE"
echo "Nodo objetivo: $TARGET_NODE"
echo

echo "[ANTES] Réplicas de Inventory:"
kubectl get pods -n "$NAMESPACE" -l app=inventory-service -o wide

POD="$(kubectl get pods -n "$NAMESPACE" \
  -l app=inventory-service \
  --field-selector "spec.nodeName=$TARGET_NODE" \
  -o jsonpath='{.items[0].metadata.name}')"

if [[ -z "$POD" ]]; then
  echo "ERROR: no existe una réplica de Inventory en $TARGET_NODE." >&2
  exit 1
fi

echo
echo "[FALLO] Eliminando $POD ..."
kubectl delete pod "$POD" -n "$NAMESPACE"

echo
echo "[DURANTE] Reserva mientras la réplica eliminada se recupera:"
HTTP_CODE="$(curl -sS -o "$TMP_RESPONSE" -w '%{http_code}' \
  -X POST "$GATEWAY_URL/api/reservations" \
  -H 'Content-Type: application/json' \
  -d "{\"event_id\":$EVENT_ID,\"user_id\":$USER_ID,\"quantity\":$QUANTITY}")"

echo "HTTP $HTTP_CODE"
python3 -m json.tool < "$TMP_RESPONSE" || cat "$TMP_RESPONSE"

python3 - "$TMP_RESPONSE" "$HTTP_CODE" <<'PY'
import json
import sys

path, code = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)

if code != "200" or data.get("status") != "CONFIRMED":
    raise SystemExit(
        f"ERROR: se esperaba HTTP 200 + CONFIRMED; se obtuvo HTTP {code} + {data.get('status')}"
    )
PY

echo
echo "[RECUPERACIÓN] Esperando que el Deployment vuelva a estar disponible ..."
kubectl rollout status deployment/inventory-service -n "$NAMESPACE" --timeout=120s
kubectl get pods -n "$NAMESPACE" -l app=inventory-service -o wide

echo
echo "=== RESULTADO ==="
echo "Pod eliminado: $POD"
echo "Reserva durante el fallo: CONFIRMED"
echo "Deployment de Inventory: recuperado"
