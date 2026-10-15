param(
    [int]$Port = 5000
)

$rootDir = $PSScriptRoot
if (-not $rootDir) { $rootDir = (Get-Location).Path }

$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://localhost:$Port/")
$listener.Prefixes.Add("http://127.0.0.1:$Port/")

try {
    $listener.Start()
    Write-Host "[*] SHIVA SOLUTION Native Server running on http://localhost:$Port"
} catch {
    Write-Host "[!] Could not bind to port $Port : $_"
    exit 1
}

$mimeTypes = @{
    ".html" = "text/html; charset=utf-8"
    ".htm"  = "text/html; charset=utf-8"
    ".css"  = "text/css; charset=utf-8"
    ".js"   = "application/javascript; charset=utf-8"
    ".json" = "application/json; charset=utf-8"
    ".jpg"  = "image/jpeg"
    ".jpeg" = "image/jpeg"
    ".png"  = "image/png"
    ".gif"  = "image/gif"
    ".svg"  = "image/svg+xml"
    ".ico"  = "image/x-icon"
    ".csv"  = "text/csv; charset=utf-8"
}

function Send-JsonResponse($response, $obj, [int]$statusCode = 200) {
    try {
        $json = $obj | ConvertTo-Json -Depth 10 -Compress
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
        $response.StatusCode = $statusCode
        $response.ContentType = "application/json; charset=utf-8"
        $response.Headers.Add("Access-Control-Allow-Origin", "*")
        $response.Headers.Add("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        $response.Headers.Add("Access-Control-Allow-Headers", "Content-Type, X-Owner-Pin")
        $response.ContentLength64 = $bytes.Length
        $response.OutputStream.Write($bytes, 0, $bytes.Length)
        $response.OutputStream.Close()
    } catch {}
}

function Send-FileResponse($response, $filePath, $contentType = $null) {
    try {
        if (-not (Test-Path $filePath -PathType Leaf)) {
            $response.StatusCode = 404
            $msg = [System.Text.Encoding]::UTF8.GetBytes("404 Not Found")
            $response.OutputStream.Write($msg, 0, $msg.Length)
            $response.OutputStream.Close()
            return
        }
        
        $ext = [System.IO.Path]::GetExtension($filePath).ToLower()
        if (-not $contentType) {
            $contentType = if ($mimeTypes.ContainsKey($ext)) { $mimeTypes[$ext] } else { "application/octet-stream" }
        }
        
        $bytes = [System.IO.File]::ReadAllBytes($filePath)
        $response.StatusCode = 200
        $response.ContentType = $contentType
        $response.Headers.Add("Access-Control-Allow-Origin", "*")
        $response.ContentLength64 = $bytes.Length
        $response.OutputStream.Write($bytes, 0, $bytes.Length)
        $response.OutputStream.Close()
    } catch {}
}

while ($listener.IsListening) {
    try {
        $context = $listener.GetContext()
        $request = $context.Request
        $response = $context.Response
        
        $path = $request.Url.AbsolutePath
        $method = $request.HttpMethod
        
        # Handle CORS OPTIONS
        if ($method -eq "OPTIONS") {
            $response.StatusCode = 200
            $response.Headers.Add("Access-Control-Allow-Origin", "*")
            $response.Headers.Add("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            $response.Headers.Add("Access-Control-Allow-Headers", "Content-Type, X-Owner-Pin")
            $response.OutputStream.Close()
            continue
        }
        
        # Route: /admin or /admin/
        if ($path -eq "/admin" -or $path -eq "/admin/") {
            $adminFile = Join-Path $rootDir "admin.html"
            Send-FileResponse $response $adminFile "text/html; charset=utf-8"
            continue
        }
        
        # Route: / or /index.html
        if ($path -eq "/" -or $path -eq "/index.html") {
            $indexFile = Join-Path $rootDir "index.html"
            Send-FileResponse $response $indexFile "text/html; charset=utf-8"
            continue
        }
        
        # API: /api/blogs
        if ($path -eq "/api/blogs") {
            $blogsFile = Join-Path $rootDir "database\blogs.json"
            if ($method -eq "GET") {
                $blogs = @()
                if (Test-Path $blogsFile) {
                    try {
                        $raw = Get-Content $blogsFile -Raw -Encoding UTF8
                        $blogs = $raw | ConvertFrom-Json
                    } catch {}
                }
                Send-JsonResponse $response @{ status = "success"; count = $blogs.Count; blogs = $blogs }
                continue
            } elseif ($method -eq "POST") {
                $reader = New-Object System.IO.StreamReader($request.InputStream, $request.ContentEncoding)
                $body = $reader.ReadToEnd()
                try {
                    $item = $body | ConvertFrom-Json
                    $blogs = @()
                    if (Test-Path $blogsFile) {
                        try {
                            $raw = Get-Content $blogsFile -Raw -Encoding UTF8
                            $blogs = @($raw | ConvertFrom-Json)
                        } catch {}
                    }
                    
                    $existingIdx = -1
                    for ($i = 0; $i -lt $blogs.Count; $i++) {
                        if ($blogs[$i].id -eq $item.id) { $existingIdx = $i; break }
                    }
                    
                    if ($existingIdx -ge 0) {
                        $blogs[$existingIdx] = $item
                    } else {
                        $blogs = @($item) + $blogs
                    }
                    
                    $blogs | ConvertTo-Json -Depth 10 | Set-Content $blogsFile -Encoding UTF8
                    Send-JsonResponse $response @{ status = "success"; message = "Blog saved successfully"; blog = $item }
                } catch {
                    Send-JsonResponse $response @{ status = "error"; message = $_.Exception.Message } 400
                }
                continue
            } elseif ($method -eq "DELETE") {
                $id = $request.QueryString["id"]
                if ($id) {
                    $blogs = @()
                    if (Test-Path $blogsFile) {
                        try {
                            $raw = Get-Content $blogsFile -Raw -Encoding UTF8
                            $blogs = @($raw | ConvertFrom-Json)
                            $blogs = @($blogs | Where-Object { $_.id -ne $id })
                            $blogs | ConvertTo-Json -Depth 10 | Set-Content $blogsFile -Encoding UTF8
                        } catch {}
                    }
                    Send-JsonResponse $response @{ status = "success"; message = "Blog deleted" }
                } else {
                    Send-JsonResponse $response @{ status = "error"; message = "Missing blog id" } 400
                }
                continue
            }
        }
        
        # API: /api/leads
        if ($path -eq "/api/leads") {
            $leadsFile = Join-Path $rootDir "database\leads.json"
            $leadsCsv = Join-Path $rootDir "database\leads.csv"
            if ($method -eq "GET") {
                $leads = @()
                if (Test-Path $leadsFile) {
                    try {
                        $raw = Get-Content $leadsFile -Raw -Encoding UTF8
                        $leads = $raw | ConvertFrom-Json
                    } catch {}
                }
                Send-JsonResponse $response @{ status = "success"; count = $leads.Count; leads = $leads }
                continue
            } elseif ($method -eq "POST") {
                $reader = New-Object System.IO.StreamReader($request.InputStream, $request.ContentEncoding)
                $body = $reader.ReadToEnd()
                try {
                    $lead = $body | ConvertFrom-Json
                    $leads = @()
                    if (Test-Path $leadsFile) {
                        try {
                            $raw = Get-Content $leadsFile -Raw -Encoding UTF8
                            $leads = @($raw | ConvertFrom-Json)
                        } catch {}
                    }
                    $now = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
                    $leadObj = [PSCustomObject]@{
                        id = "lead_" + [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
                        phone = $lead.phone
                        name = if ($lead.name) { $lead.name } else { "Customer" }
                        preferences = if ($lead.preferences) { $lead.preferences } else { "Cricket Alerts" }
                        source = if ($lead.source) { $lead.source } else { "Website" }
                        timestamp = $now
                    }
                    $leads = @($leadObj) + $leads
                    $leads | ConvertTo-Json -Depth 10 | Set-Content $leadsFile -Encoding UTF8
                    
                    $csvLine = "$($leadObj.id),$($leadObj.timestamp),+91 $($leadObj.phone),$($leadObj.name),$($leadObj.preferences),$($leadObj.source)"
                    Add-Content -Path $leadsCsv -Value $csvLine -Encoding UTF8
                    
                    Send-JsonResponse $response @{ status = "success"; message = "Lead captured"; id = $leadObj.id }
                } catch {
                    Send-JsonResponse $response @{ status = "error"; message = $_.Exception.Message } 400
                }
                continue
            }
        }
        
        # API: /api/live-scores, /api/ball-by-ball, /api/live-news
        if ($path -eq "/api/live-scores") {
            $f = Join-Path $rootDir "database\live_scores.json"
            if (Test-Path $f) { Send-FileResponse $response $f "application/json" } else { Send-JsonResponse $response @{ matches = @() } }
            continue
        }
        if ($path -eq "/api/ball-by-ball") {
            $f = Join-Path $rootDir "database\ball_by_ball.json"
            if (Test-Path $f) { Send-FileResponse $response $f "application/json" } else { Send-JsonResponse $response @{ telemetry = @{} } }
            continue
        }
        if ($path -eq "/api/live-news") {
            $f = Join-Path $rootDir "database\live_news.json"
            if (Test-Path $f) { Send-FileResponse $response $f "application/json" } else { Send-JsonResponse $response @{ news = @() } }
            continue
        }
        
        # API: /api/auth/login
        if ($path -eq "/api/auth/login") {
            $reader = New-Object System.IO.StreamReader($request.InputStream, $request.ContentEncoding)
            $body = $reader.ReadToEnd()
            $creds = $body | ConvertFrom-Json
            if (($creds.username -eq "admin" -or $creds.username -eq "shiva") -and $creds.password -eq "shiv21212929@") {
                Send-JsonResponse $response @{ status = "success"; token = "token_" + [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds(); username = $creds.username }
            } else {
                Send-JsonResponse $response @{ status = "error"; message = "Invalid username or password" } 401
            }
            continue
        }
        
        # API: /api/auth/verify-pin
        if ($path -eq "/api/auth/verify-pin") {
            $reader = New-Object System.IO.StreamReader($request.InputStream, $request.ContentEncoding)
            $body = $reader.ReadToEnd()
            $pinObj = $body | ConvertFrom-Json
            if ($pinObj.pin -eq "shiv21212929@") {
                Send-JsonResponse $response @{ status = "success"; message = "Verified" }
            } else {
                Send-JsonResponse $response @{ status = "error"; message = "Incorrect PIN" } 401
            }
            continue
        }
        
        # API: /api/leads/export
        if ($path -eq "/api/leads/export") {
            $csvFile = Join-Path $rootDir "database\leads.csv"
            $response.Headers.Add("Content-Disposition", 'attachment; filename="shiva_solution_leads.csv"')
            Send-FileResponse $response $csvFile "text/csv; charset=utf-8"
            continue
        }

        # Static files
        $cleanPath = $path.TrimStart("/").Replace("/", "\")
        $localFile = Join-Path $rootDir $cleanPath
        if (Test-Path $localFile -PathType Leaf) {
            Send-FileResponse $response $localFile
        } else {
            $response.StatusCode = 404
            $notFoundMsg = [System.Text.Encoding]::UTF8.GetBytes("404 Not Found")
            $response.OutputStream.Write($notFoundMsg, 0, $notFoundMsg.Length)
            $response.OutputStream.Close()
        }
    } catch {}
}
