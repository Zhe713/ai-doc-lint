# One-click full test run inside the api container (recommended)
# Why in-container: host venv runs go through Docker Desktop port-forwarding
# (127.0.0.1 -> WSL), which can hang under high load (psycopg waits forever on
# connect). Inside the container, db/cache are reached over the Docker network
# directly, so tests are fast and stable.
# Usage: powershell -ExecutionPolicy Bypass -File scripts-dev\run_tests.ps1
$ErrorActionPreference = "Stop"

$envFile = Join-Path (Join-Path $PSScriptRoot "..") ".env"
$u = (Select-String -Path $envFile -Pattern '^POSTGRES_USER=' | Select-Object -First 1).Line -replace '^POSTGRES_USER=',''
$testDb = (Select-String -Path $envFile -Pattern '^POSTGRES_TEST_DB=' | Select-Object -First 1).Line -replace '^POSTGRES_TEST_DB=',''
if (-not $testDb) { $testDb = "ai_doc_lint_test" }

Write-Host "[1/3] Cleaning test DB ($testDb) connections..."
docker exec ai-doc-lint-db-1 psql -U $u -d postgres -t -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$testDb' AND pid <> pg_backend_pid();" | Out-Null
Write-Host "      done"

Write-Host "[2/3] Ensuring api container is up..."
docker ps --format "{{.Names}}" | Select-String "ai-doc-lint-api-1" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "api container not running" }
Write-Host "      done"

Write-Host "[3/3] Running pytest inside api container..."
docker exec ai-doc-lint-api-1 python -m pytest tests -v
$code = $LASTEXITCODE
Write-Host "pytest exit code: $code"
exit $code
