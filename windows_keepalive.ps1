# Автопродление сессии Moodle МИРЭА: пинг /my/ каждые 20 минут.
# Запускается Планировщиком заданий Windows (см. README, раздел «Keep-alive»).
# Лог: %USERPROFILE%\.zcode\moodle_keepalive.log — строки OK / DEAD.
$cookieFile = "$env:USERPROFILE\.zcode\moodle_cookie"
$log = "$env:USERPROFILE\.zcode\moodle_keepalive.log"
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

if (-not (Test-Path $cookieFile)) {
    Add-Content -Path $log -Value "$stamp DEAD нет cookie-файла ($cookieFile)"
    exit
}
$ck = (Get-Content $cookieFile -Raw).Trim()
if ($ck -notlike "MoodleSession=*") { $ck = "MoodleSession=$ck" }

$code = 0
$body = ""
try {
    $r = Invoke-WebRequest -Uri "https://online-edu.mirea.ru/my/" `
        -Headers @{ Cookie = $ck } -UserAgent "Mozilla/5.0" `
        -TimeoutSec 30 -MaximumRedirection 0 -UseBasicParsing
    $code = [int]$r.StatusCode
    $body = $r.Content
} catch {
    if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
}

if ($code -eq 200 -and $body -match "sesskey") {
    Add-Content -Path $log -Value "$stamp OK $code"
} else {
    Add-Content -Path $log -Value "$stamp DEAD $code — обнови cookie"
}
