param(
  [string]$SystemID,
  [string]$ApmsPath,
  [string]$OutputJson,
  [string]$ChecklistPath
)

# ---- runtime prefs: loud + plain text + UTF-8 ----
$ErrorActionPreference        = 'Continue'
$InformationPreference        = 'Continue'
$VerbosePreference            = 'Continue'
$DebugPreference              = 'Continue'
$ProgressPreference           = 'Continue'   # we’ll emit progress manually
[Console]::OutputEncoding     = [Text.UTF8Encoding]::UTF8
if ($PSStyle) { $PSStyle.OutputRendering = 'PlainText' }  # kill ANSI

function Flush([string]$msg) {
  if ($null -ne $msg) {
    Write-Host $msg
    [Console]::Out.Flush()
  }
}

function Emit-All($tag, $msg) {
  # Show how each channel behaves
  Write-Host        "[HOST][$tag] $msg"
  Write-Output      "[OUT][$tag] $msg"
  Write-Verbose     "[VERBOSE][$tag] $msg"
  Write-Information "[INFO][$tag] $msg"
  Write-Warning     "[WARN][$tag] $msg"
  Write-Debug       "[DEBUG][$tag] $msg"
  [Console]::Out.Flush()
}

# ---- start ----
Emit-All 'START' "DevTest for system $SystemID"
Start-Sleep -Milliseconds 200

# Progress demo (a bunch of lines)
for ($i = 1; $i -le 10; $i++) {
  Write-Progress -Activity "DevTest progress" -Status "Step $i/10" -PercentComplete ($i*10)
  Flush ("[PROGRESS] step $i/10")
  Start-Sleep -Milliseconds 150
}

Emit-All 'PHASE' 'Deep Dive Testing initialized'
Start-Sleep -Milliseconds 200
Emit-All 'PHASE' 'Found eMASS Hardware Data'
Start-Sleep -Milliseconds 200
Emit-All 'PHASE' 'Found eMASS Software Data'
Start-Sleep -Milliseconds 200
Emit-All 'PHASE' 'Artifacts found for system'
Start-Sleep -Milliseconds 200
Emit-All 'PHASE' 'Successfully Pulled Artifact Detail Data'
Start-Sleep -Milliseconds 200
Emit-All 'TEST'  'Test 1: Validate Metadata Schema'
Start-Sleep -Milliseconds 200
Emit-All 'TEST'  'Test 2: Check Row Count Consistency'
Start-Sleep -Milliseconds 200
Emit-All 'MATCH' 'APMS Report number and eMASS APMS ID Match'
Start-Sleep -Milliseconds 200

# CSV demo
Flush ("[READ] CSV path: $ApmsPath")
try {
  if (Test-Path -LiteralPath $ApmsPath) {
    Get-Content -LiteralPath $ApmsPath | ForEach-Object {
      Flush ("[CSV] $_")
      Start-Sleep -Milliseconds 80
    }
  } else {
    Write-Error "[ERROR] CSV not found: $ApmsPath"
    [Console]::Out.Flush()
  }
} catch {
  Write-Error "[ERROR] Failed to read CSV: $($_.Exception.Message)"
  [Console]::Out.Flush()
}

# Write a small JSON file the Python side expects
Flush ("[JSON] Writing fake test results -> $OutputJson")
@(
  @{ Cell = "D10"; Value = "PASS" }
  @{ Cell = "D11"; Value = "PASS" }
  @{ Cell = "D12"; Value = "FAIL" }
  @{ Cell = "D13"; Value = "N/A" }
) | ConvertTo-Json -Depth 3 | Out-File -LiteralPath $OutputJson -Encoding utf8

Emit-All 'DONE' 'DevTest complete; handing off to Python'
Flush "[END] DevTest finished"


