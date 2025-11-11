<#
.SYNOPSIS
Starts the Azure Functions app locally (PowerShell version of startLocal.sh)

.Run from: repo root or scripts folder
#>

param(
    [switch]$VerboseHost
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Ensure we run relative to this script's location
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Move into pipeline directory
$pipelineDir = Join-Path (Split-Path $scriptDir -Parent) "pipeline"
Set-Location $pipelineDir

Write-Host "📁 Working directory: $pipelineDir" -ForegroundColor Green
Write-Host ""

# ============================================
# Step 1: Validate Prerequisites
# ============================================
Write-Host "🔍 Step 1: Validating prerequisites..." -ForegroundColor Yellow

# Check Python
try {
    $pythonVersion = python --version 2>&1
    if ($pythonVersion -match "Python (\d+)\.(\d+)") {
        $major = [int]$matches[1]
        $minor = [int]$matches[2]
        if ($major -ge 3 -and $minor -ge 10) {
            Write-Host "  ✅ Python $pythonVersion" -ForegroundColor Green
        } else {
            Write-Host "  ❌ Python version must be 3.10 or higher. Found: $pythonVersion" -ForegroundColor Red
            exit 1
        }
    }
} catch {
    Write-Host "  ❌ Python not found. Please install Python 3.10+" -ForegroundColor Red
    exit 1
}

# Check Azure Functions Core Tools
try {
    $funcVersion = func --version 2>&1
    Write-Host "  ✅ Azure Functions Core Tools v$funcVersion" -ForegroundColor Green
} catch {
    Write-Host "  ❌ Azure Functions Core Tools not found." -ForegroundColor Red
    Write-Host "     Install with: winget install Microsoft.Azure.FunctionsCoreTools" -ForegroundColor Yellow
    exit 1
}

# Check Azure CLI
try {
    $azVersion = az version --query '"azure-cli"' -o tsv 2>&1
    Write-Host "  ✅ Azure CLI v$azVersion" -ForegroundColor Green
    
    # Check if logged in
    $account = az account show 2>&1
    if ($LASTEXITCODE -eq 0) {
        $accountInfo = $account | ConvertFrom-Json
        Write-Host "  ✅ Logged in as: $($accountInfo.user.name)" -ForegroundColor Green
    } else {
        Write-Host "  ⚠️  Not logged into Azure CLI. Run: az login" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  ⚠️  Azure CLI not found (optional but recommended)" -ForegroundColor Yellow
}

Write-Host ""

# ============================================
# Step 2: Setup Python Virtual Environment
# ============================================
Write-Host "🐍 Step 2: Setting up Python virtual environment..." -ForegroundColor Yellow

# Create venv if missing
if (-not (Test-Path .venv)) {
    Write-Host "  📦 Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
    Write-Host "  ✅ Virtual environment created" -ForegroundColor Green
} else {
    Write-Host "  ✅ Virtual environment exists" -ForegroundColor Green
}

# Activate venv (Windows / PowerShell)
$activate = Join-Path .venv "Scripts\Activate.ps1"
if (-not (Test-Path $activate)) {
    Write-Error "  ❌ Activation script not found at $activate"
    exit 1
}

Write-Host "  🔄 Activating virtual environment..." -ForegroundColor Cyan
& $activate

# Upgrade pip (optional but helpful)
Write-Host "  📦 Upgrading pip..." -ForegroundColor Cyan
python -m pip install --upgrade pip --quiet

# Install dependencies
Write-Host "  📦 Installing dependencies from requirements.txt..." -ForegroundColor Cyan
pip install -r requirements.txt --quiet
Write-Host "  ✅ Dependencies installed" -ForegroundColor Green
Write-Host ""

# ============================================
# Step 3: Validate Configuration
# ============================================
Write-Host "⚙️  Step 3: Validating configuration..." -ForegroundColor Yellow

$localSettingsPath = "local.settings.json"
if (-not (Test-Path $localSettingsPath)) {
    Write-Host "  ❌ local.settings.json not found!" -ForegroundColor Red
    Write-Host "     Please create it from the template or run getRemoteSettings.ps1" -ForegroundColor Yellow
    exit 1
}

Write-Host "  ✅ local.settings.json exists" -ForegroundColor Green

# Parse and validate settings
try {
    $settings = Get-Content $localSettingsPath -Raw | ConvertFrom-Json
    
    # Check critical settings
    $requiredSettings = @(
        "FUNCTIONS_WORKER_RUNTIME",
        "AzureWebJobsStorage",
        "FUNCTIONAPP_ENV"
    )
    
    $missingSettings = @()
    foreach ($setting in $requiredSettings) {
        if (-not $settings.Values.$setting) {
            $missingSettings += $setting
        }
    }
    
    if ($missingSettings.Count -gt 0) {
        Write-Host "  ⚠️  Missing required settings:" -ForegroundColor Yellow
        foreach ($missing in $missingSettings) {
            Write-Host "     - $missing" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  ✅ All required settings present" -ForegroundColor Green
    }
    
    # Display mode
    $envMode = $settings.Values.FUNCTIONAPP_ENV
    if ($envMode -eq "local") {
        Write-Host "  🔧 Mode: LOCAL (using environment variables)" -ForegroundColor Cyan
    } else {
        Write-Host "  ☁️  Mode: CLOUD (using App Configuration)" -ForegroundColor Cyan
    }
    
    # Check if allow_environment_variables is set for local mode
    if ($envMode -eq "local") {
        $allowEnvVars = $settings.Values.allow_environment_variables
        if ($allowEnvVars -eq "true") {
            Write-Host "  ✅ Environment variables enabled for local mode" -ForegroundColor Green
        } else {
            Write-Host "  ⚠️  Consider setting allow_environment_variables=true for local mode" -ForegroundColor Yellow
        }
    }
    
} catch {
    Write-Host "  ⚠️  Could not parse local.settings.json: $_" -ForegroundColor Yellow
}

Write-Host ""

# ============================================
# Step 4: Start Azure Functions Host
# ============================================
Write-Host "🚀 Step 4: Starting Azure Functions host..." -ForegroundColor Yellow
Write-Host ""
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop the function host" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""

# Start Azure Functions host
$funcArgs = @()
if ($VerboseHost.IsPresent) {
    $funcArgs += "--verbose"
}

func start @funcArgs