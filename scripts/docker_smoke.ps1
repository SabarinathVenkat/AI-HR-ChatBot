# Smoke test of the built image. Usage:  powershell -File scripts\docker_smoke.ps1
# Needs a .env with ANTHROPIC_API_KEY. Uses a throwaway container and volume, removed at the end.
$ErrorActionPreference = "Continue"   # PowerShell 5.1 turns native stderr (e.g. "no such container") fatal under Stop
$name = "hr-smoke"; $vol = "hr_smoke_data"; $hostPort = 8010; $base = "http://127.0.0.1:$hostPort"
$secret = [Convert]::ToBase64String((1..48 | ForEach-Object { Get-Random -Maximum 256 }) -as [byte[]])

function Wait-Healthy {
    for ($i = 0; $i -lt 40; $i++) {
        try { if ((Invoke-RestMethod "$base/health" -TimeoutSec 3).status -eq "ok") { return $true } } catch {}
        Start-Sleep -Seconds 3
    }
    return $false
}
function Login($email) {
    (Invoke-RestMethod "$base/auth/login" -Method Post -ContentType "application/json" `
        -Body (@{ email = $email; password = "Welcome@123" } | ConvertTo-Json)).access_token
}

docker rm -f $name *> $null
docker run -d --name $name --env-file .env -e "JWT_SECRET=$secret" -e FIXED_DATE=2026-10-02 `
    -p "${hostPort}:8000" -v "${vol}:/data" hr-chat-agent | Out-Null
if ($LASTEXITCODE -ne 0) { throw "docker run failed" }
"started; waiting for health..."
if (-not (Wait-Healthy)) { docker logs --tail 30 $name; throw "container never became healthy" }
"1. /health ok"

"2. runs as: " + (docker exec $name id -un) + " (uid " + (docker exec $name id -u) + ")"

$page = Invoke-WebRequest "$base/" -UseBasicParsing
"3. web page: HTTP $($page.StatusCode), contains 'HR Assistant': $($page.Content -match 'HR Assistant')"
"   CSP header present: " + [bool]$page.Headers["Content-Security-Policy"] + "; X-Frame-Options: " + $page.Headers["X-Frame-Options"]

$token = Login "ravi.kumar@example-ideas2it.invalid"
$me = Invoke-RestMethod "$base/me" -Headers @{ Authorization = "Bearer $token" }
"4. login ok: $($me.name), role $($me.role)"

$bal = Invoke-RestMethod "$base/leave/balance" -Headers @{ Authorization = "Bearer $token" }
"5. balances: " + (($bal.balances | ForEach-Object { "$($_.leave_type)=$($_.available)" }) -join ", ")

"6. live chat (real model):"
$body = @{ message = "How many annual leave days do I have left?" } | ConvertTo-Json
$resp = Invoke-WebRequest "$base/chat" -Method Post -ContentType "application/json" -Body $body `
    -Headers @{ Authorization = "Bearer $token" } -UseBasicParsing -TimeoutSec 120
$answer = ($resp.Content -split "`n" | Where-Object { $_ -like 'data: {"text"*' } | ForEach-Object { ($_ -replace '^data: ', '' | ConvertFrom-Json).text }) -join ""
"   answer: $answer"
"   done event present: " + ($resp.Content -match "event: done")

"7. restart persistence:"
docker restart $name | Out-Null
if (-not (Wait-Healthy)) { docker logs --tail 30 $name; throw "did not come back healthy after restart" }
$token2 = Login "ravi.kumar@example-ideas2it.invalid"
"   after restart, login still works: $([bool]$token2)"
"   seeded once (log lines): " + ((docker logs $name 2>&1 | Select-String "seeding demo data").Count) + " seeding message(s) across both starts"

docker rm -f $name | Out-Null
docker volume rm $vol | Out-Null
"cleaned up container and volume"
