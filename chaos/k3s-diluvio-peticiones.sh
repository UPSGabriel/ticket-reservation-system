#!/usr/bin/env bash
set -Eeuo pipefail

NAMESPACE="${NAMESPACE:-ticket-system}"
LOCAL_PORT="${LOCAL_PORT:-8005}"
WINDOW_SECONDS="${WINDOW_SECONDS:-10}"
REQUESTS="${REQUESTS:-15}"

PF_LOG="/tmp/gateway-rate-pf.log"
PF_PID=""

cleanup() {
  if [[ -n "$PF_PID" ]]; then
    kill "$PF_PID" 2>/dev/null || true
    wait "$PF_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "=== DILUVIO DE PETICIONES / K3s ==="

echo
 echo "[ANTES] Réplicas del API Gateway:"
kubectl get pods -n "$NAMESPACE" -l app=api-gateway -o wide

POD="$(kubectl get pods -n "$NAMESPACE" -l app=api-gateway \
  --field-selector=status.phase=Running \
  -o jsonpath='{.items[0].metadata.name}')"

if [[ -z "$POD" ]]; then
  echo "ERROR: no hay un pod Running del API Gateway." >&2
  exit 1
fi

echo
echo "Gateway seleccionado: $POD"
echo "Abriendo port-forward exclusivo en 127.0.0.1:$LOCAL_PORT ..."
kubectl port-forward "pod/$POD" "$LOCAL_PORT:8000" -n "$NAMESPACE" \
  --address 127.0.0.1 >"$PF_LOG" 2>&1 &
PF_PID=$!

for attempt in $(seq 1 20); do
  if curl -fsS "http://127.0.0.1:$LOCAL_PORT/health" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$PF_PID" 2>/dev/null; then
    echo "ERROR: el port-forward terminó inesperadamente." >&2
    cat "$PF_LOG" >&2 || true
    exit 1
  fi
  sleep 0.5

done

if ! curl -fsS "http://127.0.0.1:$LOCAL_PORT/health" >/dev/null 2>&1; then
  echo "ERROR: el Gateway no quedó accesible por el port-forward." >&2
  cat "$PF_LOG" >&2 || true
  exit 1
fi

echo
echo "Esperando $((WINDOW_SECONDS + 1)) s para iniciar con una ventana limpia ..."
sleep $((WINDOW_SECONDS + 1))

echo
echo "[FALLO] Enviando $REQUESTS solicitudes rápidas a una sola réplica:"
CODES=""
for i in $(seq 1 "$REQUESTS"); do
  code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$LOCAL_PORT/rate-test")"
  echo "Solicitud $i -> HTTP $code"
  CODES+="$code "
done

python3 - "$CODES" <<'PY'
import sys

codes = sys.argv[1].split()
if len(codes) < 15:
    raise SystemExit("ERROR: se esperaban al menos 15 respuestas.")
if codes[:10] != ["404"] * 10:
    raise SystemExit(f"ERROR: las primeras 10 respuestas no fueron todas 404: {codes[:10]}")
if codes[10:15] != ["429"] * 5:
    raise SystemExit(f"ERROR: las solicitudes 11-15 no fueron todas 429: {codes[10:15]}")
PY

echo
echo "[EVIDENCIA] Logs de rate limiting:"
kubectl logs "$POD" -n "$NAMESPACE" --since=10m | grep 'rate limiting' || true

echo
echo "[RECUPERACIÓN] Esperando $((WINDOW_SECONDS + 1)) s ..."
sleep $((WINDOW_SECONDS + 1))
FINAL_CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$LOCAL_PORT/rate-test")"
echo "Solicitud después de recuperar ventana -> HTTP $FINAL_CODE"

if [[ "$FINAL_CODE" != "404" ]]; then
  echo "ERROR: se esperaba HTTP 404 después de expirar la ventana; se obtuvo $FINAL_CODE." >&2
  exit 1
fi

echo
echo "=== RESULTADO COMPROBADO ==="
echo "Solicitudes 1-10: HTTP 404"
echo "Solicitudes 11-15: HTTP 429"
echo "Después de la ventana: HTTP 404"
