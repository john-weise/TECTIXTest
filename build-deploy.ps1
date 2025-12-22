# build-deploy.ps1
$ErrorActionPreference = 'Stop'

$projectRoot = Get-Location
$srcDir     = Join-Path $projectRoot 'react_src'
$buildDir   = Join-Path $srcDir      'build'
$destDir    = Join-Path $projectRoot 'react_build'

Write-Host "=> Cleaning up old build at $destDir"
if (Test-Path $destDir) {
    Remove-Item $destDir -Recurse -Force
}

Write-Host "=> Building React app in $srcDir"
Push-Location $srcDir
try {
    npm run build
} catch {
    Write-Host "❌ React build failed. Stopping deployment." -ForegroundColor Red
    Pop-Location
    exit 1
}
Pop-Location

Write-Host "=> Moving new build to $destDir"
Move-Item -Path $buildDir -Destination $destDir

Write-Host "=> Removing existing container and image if they exist"
try {
    docker rm -f atoaas | Out-Null
} catch {
    Write-Host "   (No existing container to remove)"
}

try {
    docker rmi atoaas | Out-Null
} catch {
    Write-Host "   (No existing image to remove)"
}

Write-Host "=> Rebuilding Docker image"
docker build -t atoaas $projectRoot

# ⬇️ bail out cleanly if the build failed
if ($LASTEXITCODE -ne 0) {
  Write-Host "❌ Docker build failed (exit $LASTEXITCODE). Aborting run." -ForegroundColor Red
  exit 1
}

# ⬇️ double-check the image actually exists
docker image inspect atoaas:latest | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Host "❌ Image 'atoaas:latest' not found (build likely failed). Aborting run." -ForegroundColor Red
  exit 1
}

Write-Host "=> Running new container"
docker run -d --name atoaas -p 5000:5000 atoaas
if ($LASTEXITCODE -ne 0) {
  Write-Host "❌ Docker run failed (exit $LASTEXITCODE)." -ForegroundColor Red
  exit 1
}

Start-Process http://127.0.0.1:5000

Write-Host "=> Streaming container logs..."
docker logs -f atoaas

