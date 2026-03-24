$cloudflaredPath = "C:\Program Files (x86)\cloudflared\cloudflared.exe"

if (-not (Test-Path $cloudflaredPath)) {
    Write-Error "cloudflared.exe was not found at $cloudflaredPath"
    exit 1
}

& $cloudflaredPath tunnel --url http://localhost:8501 --no-autoupdate
