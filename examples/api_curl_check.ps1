$body = Get-Content -Raw -LiteralPath "$PSScriptRoot\api_fake_promo_request.json"

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8787/v0/check" `
  -ContentType "application/json" `
  -Headers @{ "Authorization" = "Bearer local-dev-key" } `
  -Body $body
