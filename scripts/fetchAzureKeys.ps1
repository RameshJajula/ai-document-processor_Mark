<#!
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

function Get-ScriptVariableValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [object]$Default = ""
    )

    $var = Get-Variable -Name $Name -Scope Script -ErrorAction SilentlyContinue
    if ($null -ne $var) {
        return $var.Value
    }
    return $Default
}

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

$resourceGroup = Get-ScriptVariableValue -Name "RESOURCE_GROUP"
if (-not $resourceGroup) {
    Write-Host "❌ RESOURCE_GROUP not found in azd environment" -ForegroundColor Red
    Write-Host "   Run 'azd env select <env-name>' first" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ Resource Group: $resourceGroup" -ForegroundColor Green
Write-Host ""

# Resolve resource identifiers
[string]$storageAccountName   = Get-ScriptVariableValue -Name "AZURE_STORAGE_ACCOUNT"
[string]$aiServiceName        = Get-ScriptVariableValue -Name "AIMULTISERVICES_NAME"
[string]$aiEndpoint           = Get-ScriptVariableValue -Name "AIMULTISERVICES_ENDPOINT"
[string]$openaiApiBase        = Get-ScriptVariableValue -Name "OPENAI_API_BASE"
[string]$openaiAccountName    = ""
[string]$cosmosAccountName    = Get-ScriptVariableValue -Name "COSMOS_DB_ACCOUNT_NAME"
[string]$cosmosDbName         = Get-ScriptVariableValue -Name "COSMOS_DB_DATABASE_NAME" -Default "conversationHistoryDB"
[string]$cosmosDbContainer    = Get-ScriptVariableValue -Name "COSMOS_DB_CONVERSATION_CONTAINER" -Default "conversationhistory"
[string]$appConfigEndpoint    = Get-ScriptVariableValue -Name "APP_CONFIGURATION_URI"
[string]$appConfigConnection  = Get-ScriptVariableValue -Name "AZURE_APPCONFIG_CONNECTION_STRING"
[string]$openaiModel          = Get-ScriptVariableValue -Name "OPENAI_MODEL" -Default "gpt-4o"
[string]$openaiApiVersion     = Get-ScriptVariableValue -Name "OPENAI_API_VERSION" -Default "2024-05-01-preview"
[string]$openaiEmbeddingModel = Get-ScriptVariableValue -Name "OPENAI_API_EMBEDDING_MODEL" -Default "text-embedding-ada-002"
[string]$nextStage            = Get-ScriptVariableValue -Name "NEXT_STAGE" -Default "silver"
[string]$promptFile           = Get-ScriptVariableValue -Name "PROMPT_FILE" -Default "prompts.yaml"

if ($openaiApiBase -and $openaiApiBase -match "https://([^.]+)\.") {
    $openaiAccountName = $matches[1]
}
if (-not $openaiAccountName) {
    $openaiAccountName = Get-ScriptVariableValue -Name "AZURE_OPENAI_ACCOUNT"
    if ($openaiAccountName) {
        $openaiApiBase = "https://$openaiAccountName.openai.azure.com/"
    }
}

if (-not $aiEndpoint -and $aiServiceName) {
    $aiEndpoint = "https://$aiServiceName.cognitiveservices.azure.com/"
}

[string]$cosmosUri = Get-ScriptVariableValue -Name "COSMOS_DB_URI"
if (-not $cosmosUri -and $cosmosAccountName) {
    $cosmosUri = "https://$cosmosAccountName.documents.azure.com:443/"
}

[string]$storageKeyValue  = ""
[string]$aiKeyValue       = ""
[string]$openaiKeyValue   = ""
[string]$cosmosKeyValue   = ""

Write-Host "🔑 Fetching service keys..." -ForegroundColor Yellow
Write-Host ""

# Storage Account Key
if ($storageAccountName) {
    Write-Host "📦 Storage Account: $storageAccountName" -ForegroundColor Cyan
    try {
        $storageKey = az storage account keys list `
            --account-name $storageAccountName `
            --resource-group $resourceGroup `
            --query "[0].value" -o tsv

        $storageKeyValue = $storageKey
        $storageConnString = "DefaultEndpointsProtocol=https;AccountName=$storageAccountName;AccountKey=$storageKey;EndpointSuffix=core.windows.net"

        Write-Host "   DataStorage connection string (optional use):" -ForegroundColor Green
        Write-Host "   $storageConnString" -ForegroundColor White
        Write-Host ""
    } catch {
        Write-Host "   ⚠️  Failed to fetch storage key: $_" -ForegroundColor Yellow
    }
} else {
    Write-Host "⚠️  AZURE_STORAGE_ACCOUNT not found in azd environment" -ForegroundColor Yellow
}

# AI Services Key
if ($aiServiceName) {
    Write-Host "🤖 AI Services: $aiServiceName" -ForegroundColor Cyan
    try {
        $aiKey = az cognitiveservices account keys list `
            --name $aiServiceName `
            --resource-group $resourceGroup `
            --query "key1" -o tsv

        $aiKeyValue = $aiKey
        Write-Host "   AIMULTISERVICES_KEY:" -ForegroundColor Green
        Write-Host "   $aiKey" -ForegroundColor White
        Write-Host ""
    } catch {
        Write-Host "   ⚠️  Failed to fetch AI Services key: $_" -ForegroundColor Yellow
    }
} else {
    Write-Host "⚠️  AIMULTISERVICES_NAME not found in azd environment" -ForegroundColor Yellow
}

# Azure OpenAI Key
if ($openaiAccountName) {
    Write-Host "🧠 Azure OpenAI: $openaiAccountName" -ForegroundColor Cyan
    try {
        $openaiKey = az cognitiveservices account keys list `
            --name $openaiAccountName `
            --resource-group $resourceGroup `
            --query "key1" -o tsv

        $openaiKeyValue = $openaiKey
        Write-Host "   OPENAI_API_KEY:" -ForegroundColor Green
        Write-Host "   $openaiKey" -ForegroundColor White
        Write-Host ""
    } catch {
        Write-Host "   ⚠️  Failed to fetch OpenAI key: $_" -ForegroundColor Yellow
    }
} else {
    Write-Host "⚠️  Unable to determine Azure OpenAI resource name" -ForegroundColor Yellow
}

# Cosmos DB Key
if ($cosmosAccountName) {
    Write-Host "🗄️  Cosmos DB: $cosmosAccountName" -ForegroundColor Cyan
    try {
        $cosmosKey = az cosmosdb keys list `
            --name $cosmosAccountName `
            --resource-group $resourceGroup `
            --query "primaryMasterKey" -o tsv

        $cosmosKeyValue = $cosmosKey
        Write-Host "   COSMOS_DB_KEY:" -ForegroundColor Green
        Write-Host "   $cosmosKey" -ForegroundColor White
        Write-Host ""
    } catch {
        Write-Host "   ⚠️  Failed to fetch Cosmos DB key: $_" -ForegroundColor Yellow
    }
} else {
    Write-Host "⚠️  COSMOS_DB_ACCOUNT_NAME not found in azd environment" -ForegroundColor Yellow
}

[string]$tenantId = Get-ScriptVariableValue -Name "AZURE_TENANT_ID"
if (-not $tenantId) {
    try {
        $tenantId = az account show --query tenantId -o tsv 2>$null
    } catch {
        $tenantId = ""
    }
}

if (-not $openaiApiBase -and $openaiAccountName) {
    $openaiApiBase = "https://$openaiAccountName.openai.azure.com/"
}

if (-not $aiEndpoint) {
    $aiEndpoint = ""
}
if (-not $openaiApiBase) {
    $openaiApiBase = ""
}
if (-not $cosmosUri) {
    $cosmosUri = ""
}

$blobServiceUri  = if ($storageAccountName) { "https://$storageAccountName.blob.core.windows.net/" } else { "https://<storage-account-name>.blob.core.windows.net/" }
$queueServiceUri = if ($storageAccountName) { "https://$storageAccountName.queue.core.windows.net/" } else { "https://<storage-account-name>.queue.core.windows.net/" }
$tableServiceUri = if ($storageAccountName) { "https://$storageAccountName.table.core.windows.net/" } else { "https://<storage-account-name>.table.core.windows.net/" }
$dataEndpoint    = if ($storageAccountName) { "https://$storageAccountName.blob.core.windows.net/" } else { "https://<storage-account-name>.blob.core.windows.net/" }

$values = [ordered]@{
    "FUNCTIONS_WORKER_RUNTIME"            = "python"
    "AZURE_FUNCTIONS_ENVIRONMENT"         = "Development"
    "FUNCTIONAPP_ENV"                     = "local"

    "_comment_storage"                    = "=== Storage Configuration ==="
    "AzureWebJobsStorage__blobServiceUri"  = $blobServiceUri
    "AzureWebJobsStorage__queueServiceUri" = $queueServiceUri
    "AzureWebJobsStorage__tableServiceUri" = $tableServiceUri
    "AzureWebJobsStorage__credential"      = "AzureCliCredential"
    "DataStorage__blobServiceUri"          = $blobServiceUri
    "DataStorage__queueServiceUri"         = $queueServiceUri
    "DataStorage__tableServiceUri"         = $tableServiceUri
    "DataStorage__credential"              = "AzureCliCredential"
    "DATA_STORAGE_ENDPOINT"                = $dataEndpoint

    "_comment_config"                     = "=== Configuration Service (Optional for local) ==="
    "APP_CONFIGURATION_URI"               = "$appConfigEndpoint"
    "AZURE_APPCONFIG_CONNECTION_STRING"   = "$appConfigConnection"
    "allow_environment_variables"         = "true"
    "AzureAppConfigurationDisable"        = "true"

    "AzureWebJobsSecretStorageType"       = "Files"
    "_comment_identity"                   = "=== Azure Identity ==="
    "AZURE_TENANT_ID"                     = "$tenantId"

    "_comment_ai"                         = "=== AI Services ==="
    "AIMULTISERVICES_ENDPOINT"            = "$aiEndpoint"
    "AIMULTISERVICES_KEY"                 = "$aiKeyValue"

    "_comment_openai"                     = "=== Azure OpenAI ==="
    "OPENAI_API_BASE"                     = "$openaiApiBase"
    "OPENAI_API_KEY"                      = "$openaiKeyValue"
    "OPENAI_MODEL"                        = "$openaiModel"
    "OPENAI_API_VERSION"                  = "$openaiApiVersion"
    "OPENAI_API_EMBEDDING_MODEL"          = "$openaiEmbeddingModel"

    "_comment_cosmos"                     = "=== Cosmos DB ==="
    "COSMOS_DB_URI"                       = "$cosmosUri"
    "COSMOS_DB_KEY"                       = "$cosmosKeyValue"
    "COSMOS_DB_DATABASE_NAME"             = "$cosmosDbName"
    "COSMOS_DB_CONVERSATION_CONTAINER"    = "$cosmosDbContainer"

    "_comment_pipeline"                   = "=== Pipeline Configuration ==="
    "NEXT_STAGE"                          = "$nextStage"
    "PROMPT_FILE"                         = "$promptFile"
}

$settings = [ordered]@{
    "IsEncrypted" = $false
    "Values"      = $values
}

$settingsJson = $settings | ConvertTo-Json -Depth 6

Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "✅ Keys fetched successfully!" -ForegroundColor Green
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "📝 Generated local.settings.json payload (copy into pipeline/local.settings.json):" -ForegroundColor Yellow
Write-Host ""
Write-Host $settingsJson
Write-Host ""

