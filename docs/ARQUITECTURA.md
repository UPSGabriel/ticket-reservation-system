# Arquitectura multinodo

## Flujo l?gico

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

Reservation Service coordina la reserva. Inventory realiza el descuento at?mico, Payment decide el estado del cobro, Notification es una dependencia secundaria y Reservation persiste el resultado en PostgreSQL.

## Distribuci?n Kubernetes

`kind-config.yaml` crea dos nodos: un `control-plane` y un `worker`. Los cinco servicios HTTP poseen dos r?plicas y reglas de distribuci?n preferida por `kubernetes.io/hostname`.

```mermaid
flowchart LR
    subgraph K[Cl?ster kind ticket-cluster]
        subgraph A[Nodo control-plane]
            G1[Gateway r?plica A]
            R1[Reservation r?plica A]
            I1[Inventory r?plica A]
            P1[Payment r?plica A]
            N1[Notification r?plica A]
        end

        subgraph B[Nodo worker]
            G2[Gateway r?plica B]
            R2[Reservation r?plica B]
            I2[Inventory r?plica B]
            P2[Payment r?plica B]
            N2[Notification r?plica B]
        end

        DB[(PostgreSQL 1 r?plica)] --- PVC[(PVC 1 GiB)]
    end
```

La posici?n de las r?plicas A/B es una distribuci?n esperada, no un nombre fijo de pod. Se confirma durante la demo con:

```powershell
kubectl get nodes -o wide
kubectl get pods -n ticket-system -o wide
```

PostgreSQL tiene una sola r?plica y un PVC `ReadWriteOnce`; el nodo concreto lo decide el scheduler. Los componentes cr?ticos Reservation e Inventory permanecen replicados entre los dos nodos.

## DNS internos

| Consumidor | Dependencia | URL interna |
|---|---|---|
| API Gateway | Reservation | `http://reservation-service:8001` |
| Reservation | Inventory | `http://inventory-service:8002` |
| Reservation | Payment | `http://payment-service:8003` |
| Reservation | Notification | `http://notification-service:8004` |
| Reservation e Inventory | PostgreSQL | `postgres:5432` |

Comprobaci?n desde Reservation Service:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\jordy-k8s.ps1 -Action dns
```

## Flujo de estados

```mermaid
flowchart TD
    A[Solicitud de reserva] --> B{Inventario disponible}
    B -- No --> C[HTTP 409]
    B -- S? --> D[Descuento at?mico]
    D --> E{Payment responde antes de 3 s}
    E -- No --> F[PAYMENT_PENDING]
    E -- S? --> G{Pago aprobado}
    G -- No --> F
    G -- S? --> H{Notification enviada}
    H -- No --> I[NOTIFICATION_PENDING]
    H -- S? --> J[CONFIRMED]
    F --> K[(Persistir reserva)]
    I --> K
    J --> K
```
