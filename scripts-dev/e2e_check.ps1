$ErrorActionPreference = 'Continue'
$base = 'http://localhost:8080'
$suffix = Get-Random -Maximum 999999
$memberName = "user$suffix"
$lockName = "lock$suffix"
function Req($method, $path, $body, $token, $refreshToken) {
    $headers = @{}
    if ($token) { $headers['Authorization'] = "Bearer $token" }
    if ($refreshToken) { $headers['x-refresh-token'] = $refreshToken }
    $json = if ($null -ne $body) { $body | ConvertTo-Json -Compress } else { $null }
    try {
        $resp = Invoke-WebRequest -Uri "$base$path" -Method $method -Headers $headers -Body $json -ContentType 'application/json' -UseBasicParsing
        return [pscustomobject]@{ Status = [int]$resp.StatusCode; Body = $resp.Content }
    } catch {
        $r = $_.Exception.Response
        if ($r) {
            $sr = New-Object System.IO.StreamReader($r.GetResponseStream())
            return [pscustomobject]@{ Status = [int]$r.StatusCode; Body = $sr.ReadToEnd() }
        }
        throw
    }
}

Write-Output '--- 1. GET /health via nginx'
(Req 'GET' '/health').Body

Write-Output '--- 2. GET / (SPA)'
$spa = Req 'GET' '/'
Write-Output ("status={0}, has_app_div={1}" -f $spa.Status, ($spa.Body -match 'id="app"'))

Write-Output '--- 3. setup/status before admin'
(Req 'GET' '/api/v1/setup/status').Body

Write-Output '--- 4. create initial admin (409 is OK if already created)'
$r = Req 'POST' '/api/v1/setup/admin' @{ username = 'boss_admin'; password = 'AdminPass123' }
Write-Output ("setup status={0} body={1}" -f $r.Status, $r.Body)
$setupLogin = Req 'POST' '/api/v1/auth/login' @{ username = 'boss_admin'; password = 'AdminPass123' }
Write-Output ("admin login status={0}" -f $setupLogin.Status)
$adminAccess = ($setupLogin.Body | ConvertFrom-Json).access_token

Write-Output '--- 5. setup again -> expect 409'
Write-Output ("status={0}" -f (Req 'POST' '/api/v1/setup/admin' @{ username = 'hacker'; password = 'Whatever123' }).Status)

Write-Output '--- 6. lockout on throwaway user: 5 wrong logins -> expect 429 by the 6th'
Req 'POST' '/api/v1/auth/register' @{ username = $lockName; password = 'LockPass123' } | Out-Null
1..5 | ForEach-Object {
    $rr = Req 'POST' '/api/v1/auth/login' @{ username = $lockName; password = 'wrong' }
    Write-Output ("  attempt {0} status={1}" -f $_, $rr.Status)
}
$rr = Req 'POST' '/api/v1/auth/login' @{ username = $lockName; password = 'LockPass123' }
Write-Output ("  correct password while locked status={0} (expect 429)" -f $rr.Status)

Write-Output '--- 7. register + login member'
$reg = Req 'POST' '/api/v1/auth/register' @{ username = $memberName; password = 'AlicePass123' }
Write-Output ("register status={0}" -f $reg.Status)
$login = Req 'POST' '/api/v1/auth/login' @{ username = $memberName; password = 'AlicePass123' }
Write-Output ("login status={0}" -f $login.Status)
$tokens = $login.Body | ConvertFrom-Json
$access = $tokens.access_token; $refresh = $tokens.refresh_token

Write-Output '--- 8. /users/me'
(Req 'GET' '/api/v1/users/me' $null $access).Body

Write-Output '--- 9. no token -> expect 401'
Write-Output ("status={0}" -f (Req 'GET' '/api/v1/users/me').Status)

Write-Output '--- 10. member hits admin -> expect 403'
Write-Output ("status={0}" -f (Req 'GET' '/api/v1/admin/users' $null $access).Status)

Write-Output '--- 11. admin lists users -> expect 200'
$r = Req 'GET' '/api/v1/admin/users' $null $adminAccess
$users = @($r.Body | ConvertFrom-Json)
Write-Output ("status={0}, user_count={1}" -f $r.Status, $users.Count)

Write-Output '--- 12. refresh rotation via JSON body'
$r1 = Req 'POST' '/api/v1/auth/refresh' @{ refresh_token = $refresh }
Write-Output ("refresh status={0}" -f $r1.Status)
$newTokens = $r1.Body | ConvertFrom-Json
$newAccess = $newTokens.access_token; $newRefresh = $newTokens.refresh_token
$rOld = Req 'POST' '/api/v1/auth/refresh' @{ refresh_token = $refresh }
Write-Output ("reuse old refresh status={0} (expect 401)" -f $rOld.Status)
Write-Output ("new access works on /me status={0}" -f (Req 'GET' '/api/v1/users/me' $null $newAccess).Status)

Write-Output '--- 13. admin closes open registration'
$r = Req 'PATCH' '/api/v1/admin/settings' @{ open_registration = $false } $adminAccess
Write-Output ("patch status={0} body={1}" -f $r.Status, $r.Body)
$r = Req 'POST' '/api/v1/auth/register' @{ username = 'bob'; password = 'BobPass12345' }
Write-Output ("register while closed status={0} (expect 403)" -f $r.Status)
Req 'PATCH' '/api/v1/admin/settings' @{ open_registration = $true } $adminAccess | Out-Null

Write-Output '--- 14. logout then refresh -> expect 204 then 401'
$r = Req 'POST' '/api/v1/auth/logout' $null $newAccess $newRefresh
Write-Output ("logout status={0} (expect 204)" -f $r.Status)
$r = Req 'POST' '/api/v1/auth/refresh' @{ refresh_token = $newRefresh }
Write-Output ("refresh after logout status={0} (expect 401)" -f $r.Status)

Write-Output '--- 15. validation: short password -> expect 422'
Write-Output ("status={0}" -f (Req 'POST' '/api/v1/auth/register' @{ username = 'shorty'; password = '123' }).Status)

Write-Output '=== E2E DONE ==='
