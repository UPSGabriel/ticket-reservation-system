# Evidencias de la práctica

Este archivo es el Índice de evidencias. No se deben marcar elementos como completados hasta ejecutar el clúster real.

## Convención de archivos

Guardar las capturas dentro de `docs/evidencias/`:

```text
01_cluster_dos_nodos.png
02_distribucion_pods.png
03_servicios_dns.png
04_reserva_normal_confirmed.png
05_inventario_fantasma_durante.png
06_inventario_fantasma_recuperado.png
07_pasarela_lenta_configuracion.png
08_pasarela_lenta_payment_pending.png
09_pasarela_lenta_logs.png
10_pasarela_lenta_postgres.png
11_pasarela_lenta_recuperacion.png
12_diluvio_http_429.png
13_diluvio_recuperacion.png
14_carrera_respuestas.png
15_carrera_inventario_cero.png
```

## Checklist

| Evidencia | Comando o fuente | Estado inicial |
|---|---|---|
| Dos nodos `Ready` | `kubectl get nodes -o wide` | Pendiente de captura final |
| Réplicas distribuidas | `kubectl get pods -n ticket-system -o wide` | Pendiente de captura final |
| Services y DNS | `scripts/jordy-k8s.ps1 -Action dns` | Pendiente de ejecución final |
| Reserva normal | POST al Gateway | Pendiente de ejecución final |
| Inventario Fantasma | `chaos/gabo-inventario-fantasma.ps1` | Probado por Gabriel; falta ordenar captura final |
| Pasarela Lenta | `chaos/jordy-pasarela-lenta.ps1` | Script listo; falta ejecución Kubernetes |
| Diluvio | `chaos/gabo-diluvio-peticiones.ps1` | Probado por Gabriel; falta ordenar captura final |
| Condición de Carrera | `chaos/gabo-condicion-carrera.ps1` | Probado por Gabriel; falta ordenar captura final |
| Recuperación final | pods y reserva nueva | Pendiente de captura final |

## Qué debe verse en cada fallo

Cada conjunto debe incluir:

1. Estado antes del fallo.
2. Comando que activa el fallo.
3. Respuesta o estado durante el fallo.
4. Logs que muestran la defensa.
5. Estado después de recuperar.

Para Pasarela Lenta son imprescindibles `PAYMENT_DELAY_SECONDS=20`, el log de espera, el timeout/fallback, `PAYMENT_PENDING`, la fila PostgreSQL, la restauración a cero y una nueva reserva `CONFIRMED`.
