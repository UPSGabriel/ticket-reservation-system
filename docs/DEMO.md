# Guion de demo en vivo

Duración objetivo: 12 a 14 minutos. Ambos integrantes participan activamente.

## Preparación antes de clase

1. Confirmar Docker Desktop y el clúster.
2. Publicar todas las imágenes.
3. Desplegar Gabo y Jordy.
4. Confirmar dos nodos, pods `Running`, réplicas y DNS.
5. Detener Docker Compose y abrir el port-forward del Gateway.
6. Abrir cuatro terminales: estado, port-forward, scripts y logs.

Comandos:

```powershell
kubectl get nodes -o wide
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-k8s.ps1 -Action deploy
powershell -ExecutionPolicy Bypass -File .\scripts\jordy-k8s.ps1 -Action deploy
powershell -ExecutionPolicy Bypass -File .\scripts\jordy-k8s.ps1 -Action dns
docker compose down
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-k8s.ps1 -Action forward
```

## Minuto 0–2: arquitectura – Gabriel

Mostrar:

```powershell
kubectl get nodes -o wide
kubectl get pods -n ticket-system -o wide
kubectl get services -n ticket-system
```

Explicar los seis componentes, las dos réplicas de servicios y el PVC de PostgreSQL.

## Minuto 2–3: flujo normal – Jordy

Desactivar fallos aleatorios y crear una reserva desde Swagger o PowerShell. Mostrar `CONFIRMED`, Payment `CONFIRMED`, Notification `SENT` y la fila guardada.

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/reservations -ContentType application/json -Body '{"event_id":1,"user_id":7001,"quantity":1}' | ConvertTo-Json -Depth 10
```

## Minuto 3–5: Inventario Fantasma – Gabriel

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-inventario-fantasma.ps1
```

Antes: dos réplicas `Ready`.

Durante: se elimina una réplica y la segunda continúa disponible.

Después: Kubernetes crea un pod nuevo y vuelve a dos réplicas.

## Minuto 5–8: Pasarela Lenta – Jordy

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\jordy-pasarela-lenta.ps1
```

Antes: reserva `CONFIRMED`.

Durante: Payment anuncia 20 segundos; Reservation aplica timeout a los 3 segundos y responde HTTP 200 con `PAYMENT_PENDING`.

Después: el script restaura demora cero y obtiene otra reserva `CONFIRMED`.

Mostrar también la consulta PostgreSQL incluida en el script.

## Minuto 8–10: Diluvio de Peticiones – Gabriel

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-diluvio-peticiones.ps1
```

Antes: Gateway responde normalmente.

Durante: las solicitudes que exceden la ventana reciben HTTP 429.

Después: luego de 10 segundos vuelve a aceptar solicitudes.

## Minuto 10–12: Condición de Carrera – Gabriel y Jordy

Gabriel explica el último asiento y Jordy ejecuta:

```powershell
powershell -ExecutionPolicy Bypass -File .\chaos\gabo-condicion-carrera.ps1
```

Resultado: una solicitud HTTP 200, otra HTTP 409 e inventario final cero.

## Minuto 12–14: cierre – ambos

Jordy resume timeout y fallback. Gabriel resume réplicas, autorrecuperación, rate limiting y operación atómica.

Verificación final:

```powershell
kubectl get pods -n ticket-system -o wide
kubectl get deployments -n ticket-system
kubectl get events -n ticket-system --sort-by=.lastTimestamp
```

## Plan de contingencia

- Guardar capturas y logs antes de la clase.
- Mantener una terminal con el port-forward sin reutilizarla.
- Si una imagen no descarga, comprobar el nombre exacto y la sesión de Docker Hub.
- Si el Gateway devuelve 429 durante otra prueba, esperar 11 segundos.
- Si un evento queda sin inventario, usar otro evento o restablecer sus asientos.
- Si un script falla, Pasarela Lenta restaura Payment en su bloque `finally`.

No se necesita Kubernetes Dashboard ni Grafana. Las salidas del terminal, logs, respuestas JSON y filas PostgreSQL cumplen el requisito de evidencia.
