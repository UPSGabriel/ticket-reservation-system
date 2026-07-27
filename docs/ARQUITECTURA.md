# Arquitectura multinodo

## Flujo lógico

```mermaid
flowchart TD
    C[Cliente / Swagger] --> G[API Gateway :8000]
    G --> R[Reservation Service :8001]
    R --> I[Inventory Service :8002]
    R --> P[Payment Service :8003]
    R --> N[Notification Service :8004]
    R --> DB[(PostgreSQL :5432)]
    I --> DB
```

Reservation Service coordina la reserva. Inventory realiza el descuento atómico, Payment decide el estado del cobro, Notification es una dependencia secundaria y Reservation persiste el resultado en PostgreSQL.

## Distribución Kubernetes

`kind-config.yaml` crea dos nodos: un `control-plane` y un `worker`. Los cinco servicios HTTP poseen dos réplicas y reglas de distribución preferida por `kubernetes.io/hostname`.

```mermaid
flowchart LR
    subgraph K[Clúster kind ticket-cluster]
        subgraph A[Nodo control-plane]
            G1[Gateway réplica A]
            R1[Reservation réplica A]
            I1[Inventory réplica A]
            P1[Payment réplica A]
            N1[Notification réplica A]
        end

        subgraph B[Nodo worker]
            G2[Gateway réplica B]
            R2[Reservation réplica B]
            I2[Inventory réplica B]
            P2[Payment réplica B]
            N2[Notification réplica B]
        end

        DB[(PostgreSQL 1 réplica)] --- PVC[(PVC 1 GiB)]
    end
```

La posición de las réplicas A/B es una distribución esperada, no un nombre fijo de pod. Se confirma durante la demo con:

```powershell
kubectl get nodes -o wide
kubectl get pods -n ticket-system -o wide
```

PostgreSQL tiene una sola réplica y un PVC `ReadWriteOnce`; el nodo concreto lo decide el scheduler. Los componentes críticos Reservation e Inventory permanecen replicados entre los dos nodos.

## DNS internos

| Consumidor | Dependencia | URL interna |
|---|---|---|
| API Gateway | Reservation | `http://reservation-service:8001` |
| Reservation | Inventory | `http://inventory-service:8002` |
| Reservation | Payment | `http://payment-service:8003` |
| Reservation | Notification | `http://notification-service:8004` |
| Reservation e Inventory | PostgreSQL | `postgres:5432` |

Comprobación desde Reservation Service:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\jordy-k8s.ps1 -Action dns
```

## Flujo de estados

```mermaid
flowchart TD
    A[Solicitud de reserva] --> B{Inventario disponible}
    B -- No --> C[HTTP 409]
    B -- Sí --> D[Descuento atómico]
    D --> E{Payment responde antes de 3 s}
    E -- No --> F[PAYMENT_PENDING]
    E -- Sí --> G{Pago aprobado}
    G -- No --> F
    G -- Sí --> H{Notification enviada}
    H -- No --> I[NOTIFICATION_PENDING]
    H -- Sí --> J[CONFIRMED]
    F --> K[(Persistir reserva)]
    I --> K
    J --> K
```
