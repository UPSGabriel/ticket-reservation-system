param(
    [string]$GatewayUrl = "http://localhost:8000",
    [string]$Namespace = "ticket-system"
)

$ErrorActionPreference = "Stop"

Write-Host "=== CONDICIÓN DE CARRERA ==="
Write-Host "Preparando un único asiento para el evento 3..."

kubectl exec -n $Namespace deployment/postgres -- psql `
    -U ticket_user `
    -d ticket_db `
    -c "UPDATE inventory SET available = 1, updated_at = CURRENT_TIMESTAMP WHERE event_id = 3;"

Add-Type -AssemblyName System.Net.Http
$client = [System.Net.Http.HttpClient]::new()

$content1 = [System.Net.Http.StringContent]::new(
    '{"event_id":3,"user_id":301,"quantity":1}',
    [System.Text.Encoding]::UTF8,
    "application/json"
)

$content2 = [System.Net.Http.StringContent]::new(
    '{"event_id":3,"user_id":302,"quantity":1}',
    [System.Text.Encoding]::UTF8,
    "application/json"
)

try {
    $task1 = $client.PostAsync("$GatewayUrl/api/reservations", $content1)
    $task2 = $client.PostAsync("$GatewayUrl/api/reservations", $content2)

    [System.Threading.Tasks.Task]::WaitAll(
        [System.Threading.Tasks.Task[]]@($task1, $task2)
    )

    Write-Host "`n=== USUARIO 301 ==="
    Write-Host "HTTP:" ([int]$task1.Result.StatusCode)
    Write-Host $task1.Result.Content.ReadAsStringAsync().Result

    Write-Host "`n=== USUARIO 302 ==="
    Write-Host "HTTP:" ([int]$task2.Result.StatusCode)
    Write-Host $task2.Result.Content.ReadAsStringAsync().Result
}
finally {
    $client.Dispose()
}

Write-Host "`n=== VERIFICACIÓN EN POSTGRESQL ==="
kubectl exec -n $Namespace deployment/postgres -- psql `
    -U ticket_user `
    -d ticket_db `
    -c "SELECT event_id, available FROM inventory WHERE event_id = 3; SELECT user_id, event_id, quantity, status FROM reservations WHERE event_id = 3 ORDER BY created_at DESC;"
