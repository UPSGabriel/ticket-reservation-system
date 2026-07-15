# Parte GABO en Kubernetes

## Objetivo de esta etapa

Desplegar en Kubernetes los componentes preparados por GABO:

- API Gateway
- Reservation Service
- Inventory Service
- PostgreSQL

Los servicios críticos tienen dos réplicas. Kubernetes intenta distribuirlas entre nodos distintos mediante `topologySpreadConstraints` y anti-afinidad.

## Archivos

```text
k8s/gabo/all.yaml
scripts/gabo-images.ps1
scripts/gabo-k8s.ps1
```

## 1. Construir y publicar imágenes

Iniciar sesión en Docker Hub:

```powershell
docker login
```

Construir y publicar las tres imágenes:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-images.ps1 -Action all
```

Imágenes utilizadas:

```text
upsgabriel/ticket-api-gateway:1.0.0
upsgabriel/ticket-reservation-service:1.0.0
upsgabriel/ticket-inventory-service:1.0.0
```

## 2. Comprobar el clúster

```powershell
kubectl get nodes -o wide
```

Para la entrega final deben aparecer por lo menos dos nodos o sitios Kubernetes.

## 3. Desplegar

Antes de usar el port-forward, detener Docker Compose para liberar el puerto 8000:

```powershell
docker compose down
```

Aplicar los manifiestos y esperar las réplicas:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-k8s.ps1 -Action deploy
```

## 4. Verificar distribución

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-k8s.ps1 -Action status
```

La columna `NODE` de `kubectl get pods -o wide` permite comprobar en qué nodo quedó cada réplica.

## 5. Abrir Swagger

En una terminal nueva:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-k8s.ps1 -Action forward
```

Mantener esa terminal abierta y visitar:

```text
http://localhost:8000/docs
```

Reserva de prueba:

```json
{
  "event_id": 1,
  "user_id": 101,
  "quantity": 2
}
```

Mientras Jordy termina Pagos y Notificaciones, el resultado esperado es `PAYMENT_PENDING`. Inventario debe descontarse y la reserva debe persistirse.

## 6. Revisar logs

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-k8s.ps1 -Action logs
```

## 7. Eliminar el despliegue

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\gabo-k8s.ps1 -Action delete
```

## Estado de la práctica

Con esta etapa queda preparada la infraestructura Kubernetes de la parte GABO. Todavía faltan:

- Payment Service y Notification Service.
- Incorporar el segundo nodo o segundo sitio junto con Jordy.
- Scripts de los cuatro fallos elegidos.
- Evidencias, guion de demo e informe de los dos fallos teóricos.
