<#
.SYNOPSIS
Fetches Azure service keys and displays them for manual configuration

.DESCRIPTION
This script retrieves keys from Azure services and displays them so you can manually
update your local.settings.json file.

.EXAMPLE
.\fetchAzureKeys.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "Azure Service Keys Fetcher" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""

# Load azd environment
Write-Host "📦 Loading azd environment..." -ForegroundColor Yellow
azd env get-values | ForEach-Object {
    if ($_ -match '^(?<key>[^=]+)=(?<val>.*)$') {
        $k = $matches.key.Trim()
        $v = $matches.val
        if ($v.Length -ge 2 -and $v.StartsWith('"') -and $v.EndsWith('"')) {
            $v = $v.Substring(1, $v.Length - 2)
        }
        Set-Variable -Name $k -Value $v -Scope Script -Force
    }
}

if (-not $RESOURCE_GROUP) {
    Write-Host "❌ RESOURCE_GROUP not found in azd environment" -ForegroundColor Red
    Write-Host "   Run 'azd env select <env-name>' first" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ Resource Group: $RESOURCE_GROUP" -ForegroundColor Green
Write-Host ""

# Fetch keys
Write-Host "🔑 Fetching service keys..." -ForegroundColor Yellow
Write-Host ""

# Storage Account Key
if ($AZURE_STORAGE_ACCOUNT) {
    Write-Host "📦 Storage Account: $AZURE_STORAGE_ACCOUNT" -ForegroundColor Cyan
    try {
        $storageKey = az storage account keys list `
            --account-name $AZURE_STORAGE_ACCOUNT `
            --resource-group $RESOURCE_GROUP `
            --query "[0].value" -o tsv
        
        $storageConnString = "DefaultEndpointsProtocol=https;AccountName=$AZURE_STORAGE_ACCOUNT;AccountKey=$storageKey;EndpointSuffix=core.windows.net"
        
        Write-Host "   DataStorage:" -ForegroundColor Green
        Write-Host "   $storageConnString" -ForegroundColor White
        Write-Host ""
    } catch {
        Write-Host "   ⚠️  Failed to fetch storage key: $_" -ForegroundColor Yellow
    }
}

# AI Services Key
if ($AIMULTISERVICES_NAME) {
    Write-Host "🤖 AI Services: $AIMULTISERVICES_NAME" -ForegroundColor Cyan
    try {
        $aiKey = az cognitiveservices account keys list `
            --name $AIMULTISERVICES_NAME `
            --resource-group $RESOURCE_GROUP `
            --query "key1" -o tsv
        
        Write-Host "   AIMULTISERVICES_KEY:" -ForegroundColor Green
        Write-Host "   $aiKey" -ForegroundColor White
        Write-Host ""
    } catch {
        Write-Host "   ⚠️  Failed to fetch AI Services key: $_" -ForegroundColor Yellow
    }
}

# Azure OpenAI Key
if ($OPENAI_API_BASE -match "https://([^.]+)\.") {
    $openaiName = $matches[1]
    Write-Host "🧠 Azure OpenAI: $openaiName" -ForegroundColor Cyan
    try {
        $openaiKey = az cognitiveservices account keys list `
            --name $openaiName `
            --resource-group $RESOURCE_GROUP `
            --query "key1" -o tsv
        
        Write-Host "   OPENAI_API_KEY:" -ForegroundColor Green
        Write-Host "   $openaiKey" -ForegroundColor White
        Write-Host ""
    } catch {
        Write-Host "   ⚠️  Failed to fetch OpenAI key: $_" -ForegroundColor Yellow
    }
}

# Cosmos DB Key
if ($COSMOS_DB_ACCOUNT_NAME) {
    Write-Host "🗄️  Cosmos DB: $COSMOS_DB_ACCOUNT_NAME" -ForegroundColor Cyan
    try {
        $cosmosKey = az cosmosdb keys list `
            --name $COSMOS_DB_ACCOUNT_NAME `
            --resource-group $RESOURCE_GROUP `
            --query "primaryMasterKey" -o tsv
        
        Write-Host "   COSMOS_DB_KEY:" -ForegroundColor Green
        Write-Host "   $cosmosKey" -ForegroundColor White
        Write-Host ""
    } catch {
        Write-Host "   ⚠️  Failed to fetch Cosmos DB key: $_" -ForegroundColor Yellow
    }
}

Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "✅ Keys fetched successfully!" -ForegroundColor Green
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "📝 Copy these values into your pipeline/local.settings.json file" -ForegroundColor Yellow
Write-Host ""

