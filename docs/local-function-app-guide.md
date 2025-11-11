## Local Function App Guide

This guide documents the exact repository changes that enable reliable local development, explains how the new logic behaves in local vs. cloud scenarios, and lists the steps required to bring up the Function App on a fresh clone.

> **Who should read this?**  
> Anyone cloning the repo or reviewing the delta between the base branch and the current working branch so they can understand *what* changed, *why* we changed it, and *how* to configure their environment.

### Change Log (What & Why)
| File / Asset | Summary of Change | Local Impact | Cloud Impact |
| --- | --- | --- | --- |
| `pipeline/configuration/configuration.py` | Added `FUNCTIONAPP_ENV` awareness, customizes `DefaultAzureCredential`, and falls back to environment variables when App Configuration is disabled. | Lets local devs rely on CLI tokens or API keys without pulling remote App Config. | Still uses Managed Identity/App Config when `FUNCTIONAPP_ENV=cloud`. |
| `pipeline/pipelineUtils/blob_functions.py` | Prefers connection string; otherwise reuses shared credential object. | Works with Azurite or shared keys; compatible with CLI tokens. | Uses Managed Identity seamlessly when deployed. |
| `pipeline/pipelineUtils/db.py` | Adds factory that picks Cosmos key in local mode, token otherwise. | Can test with primary key while local; no firewall changes needed. | Uses AAD token in production as before. |
| `pipeline/activities/runDocIntel.py` | Chooses API key in local mode, token in cloud. | Immediate success with locally stored key; optional MI usage. | Uses Managed Identity automatically. |
| `pipeline/pipelineUtils/azure_openai.py` | Same pattern for Azure OpenAI client creation. | Local API key runs; no need for app role assignments. | Managed Identity token flow remains. |
| `pipeline/host.json`, `pipeline/configuration/host.json` | Disables App Configuration extension locally. | Prevents host from contacting App Config when we’re intentionally using env vars. | No change once deployed; extension can be re-enabled in published settings if needed. |
| `scripts/startLocal.ps1` | Validates tools, bootstraps venv, checks `local.settings.json`, launches host with verbose output. | One command to get a clean local environment. | Not used in cloud. |
| `scripts/fetchAzureKeys.ps1` *(new)* | Prints sanitized keys for all dependent services. | Fast way to populate `local.settings.json` when key auth is permitted. | Not used in cloud. |
| `pipeline/local.settings.template.json` *(new)* | Safe template with explanatory comments and placeholders. | Provides guardrails for new devs. | Not shipped to cloud deployments. |
| `docs/local-function-app-guide.md` *(this file)* | Captures all the above plus detailed setup and troubleshooting guidance. | Source of truth for local onboarding. | Served as documentation only. |

### Detailed File Notes
#### `pipeline/configuration/configuration.py`
Core responsibilities:
- Detects the intent via `FUNCTIONAPP_ENV` (`local` vs `cloud`).
- Builds a `DefaultAzureCredential` excluding Managed Identity locally but embracing it in cloud.
- Allows environment variables to override App Configuration when `allow_environment_variables=true`.
- Supplies new helper methods (`get_storage_config`, `get_openai_config`, etc.) that downstream modules now consume.  
```30:104:pipeline/configuration/configuration.py
        self.env_mode = os.environ.get('FUNCTIONAPP_ENV', 'cloud').lower()
        # ...
        if self.env_mode == 'local' and os.environ.get("allow_environment_variables", "false").lower() == "true":
            logger.info("📝 LOCAL mode: Using environment variables only (skipping App Configuration)")
            self.config = None
# ...
    def get_openai_config(self) -> dict:
        """Get Azure OpenAI configuration."""
        return {
            'endpoint': self.get_value('OPENAI_API_BASE'),
            'key': self.try_get_value('OPENAI_API_KEY'),
            'model': self.get_value('OPENAI_MODEL'),
            'api_version': self.get_value('OPENAI_API_VERSION'),
            'embedding_model': self.get_value('OPENAI_API_EMBEDDING_MODEL')
        }
```
**Why:** Local developers can work fully offline (from App Config) while keeping the production behavior unchanged. The credential tuning also eliminates Managed Identity calls (IMDS) when running on a laptop.

#### `pipeline/pipelineUtils/blob_functions.py`
- Instantiates `BlobServiceClient` with a connection string when available, logging fallbacks, and enforces HTTPS when using token credentials.  
```16:33:pipeline/pipelineUtils/blob_functions.py
if storage_connection:
    try:
        blob_service_client = BlobServiceClient.from_connection_string(storage_connection)
        logging.info("Initialized BlobServiceClient using connection string.")
    except Exception as ex:
        logging.warning(f"Failed to create BlobServiceClient from connection string: {ex}")
# ...
blob_service_client = BlobServiceClient(account_url=storage_endpoint, credential=config.credential)
```
**Why:** The storage account has shared-key auth disabled in production, but developers often need Azurite or connection strings locally. This pattern covers both without additional config.

#### `pipeline/pipelineUtils/db.py`
- Encapsulates Cosmos client creation; uses local key when supplied and prints meaningful log messages.  
```10:22:pipeline/pipelineUtils/db.py
if config.is_local_mode() and COSMOS_DB_KEY:
    logging.info("Initializing CosmosClient with key credential (local mode).")
    return CosmosClient(COSMOS_DB_URI, credential=COSMOS_DB_KEY)
logging.info("Initializing CosmosClient with DefaultAzureCredential.")
return CosmosClient(COSMOS_DB_URI, credential=config.credential)
```
**Why:** Cosmos accounts often block public IPs and disallow key auth. Local key injection avoids firewall churn, while cloud mode still honors AAD-only restrictions.

#### `pipeline/activities/runDocIntel.py`
- Lazily builds a Document Intelligence client with either an API key or the shared credential.  
```17:29:pipeline/activities/runDocIntel.py
if config.is_local_mode() and doc_config.get("key"):
    logging.info("Initializing DocumentIntelligenceClient with API key (local mode).")
    document_intel_client = DocumentIntelligenceClient(
        endpoint=doc_config["endpoint"], credential=AzureKeyCredential(doc_config["key"])
    )
else:
    logging.info("Initializing DocumentIntelligenceClient with DefaultAzureCredential.")
    document_intel_client = DocumentIntelligenceClient(
        endpoint=doc_config["endpoint"], credential=config.credential
    )
```
**Why:** Enables immediate local testing with key-based auth while letting App Service use Managed Identity in production.

#### `pipeline/pipelineUtils/azure_openai.py`
- Mirrors the same toggle for Azure OpenAI; reuses `config.credential` to fetch AAD tokens when keys are absent.  
```16:31:pipeline/pipelineUtils/azure_openai.py
if config.is_local_mode() and OPENAI_API_KEY:
    logging.info("Initializing AzureOpenAI client with API key (local mode).")
    return AzureOpenAI(
        api_key=OPENAI_API_KEY,
        api_version=OPENAI_API_VERSION,
        azure_endpoint=OPENAI_API_BASE
    )
logging.info("Initializing AzureOpenAI client with Azure AD token.")
token = config.credential.get_token("https://cognitiveservices.azure.com/.default").token
return AzureOpenAI(
    azure_ad_token=token,
    api_version=OPENAI_API_VERSION,
    azure_endpoint=OPENAI_API_BASE
)
```
**Why:** Eliminates the need for local app role assignments while preserving cloud security posture.

#### `pipeline/host.json` & `pipeline/configuration/host.json`
- Disables the App Configuration extension when we are in development.  
```1:11:pipeline/host.json
{
  "version": "2.0",
  "extensionBundle": {
    "id": "Microsoft.Azure.Functions.ExtensionBundle",
    "version": "[4.*, 5.0.0)"
  },
  "extensions": {
    "appConfiguration": {
      "enabled": false
    }
  }
}
```
**Why:** Prevents the host runtime from trying to hit App Configuration when we explicitly want to run from env vars only.

#### `scripts/startLocal.ps1`
- Adds four structured steps: prerequisites, virtual environment, configuration validation, and host startup. Emits emoji-prefixed logs so developers can follow progress at a glance.  
```22:155:scripts/startLocal.ps1
Write-Host "🔍 Step 1: Validating prerequisites..." -ForegroundColor Yellow
# ...
Write-Host "🐍 Step 2: Setting up Python virtual environment..." -ForegroundColor Yellow
# ...
Write-Host "⚙️  Step 3: Validating configuration..." -ForegroundColor Yellow
# ...
func start --verbose
```
**Why:** Creates a deterministic way to start the Function App locally across laptops.

#### `scripts/fetchAzureKeys.ps1` *(new)*
- Pulls keys from Storage, Document Intelligence, Azure OpenAI, and Cosmos using the `az` CLI, echoing sanitized results for manual use.  
```16:118:scripts/fetchAzureKeys.ps1
Write-Host "Azure Service Keys Fetcher"
# ...
Write-Host "🔑 Fetching service keys..." -ForegroundColor Yellow
# ...
Write-Host "📝 Copy these values into your pipeline/local.settings.json file" -ForegroundColor Yellow
```
**Why:** Simplifies populating the template when key auth is temporarily allowed.

#### `pipeline/local.settings.template.json` *(new)*
- Offers a known-good structure for `local.settings.json` with comments describing each block.  
```1:40:pipeline/local.settings.template.json
{
  "IsEncrypted": false,
  "Values": {
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "FUNCTIONAPP_ENV": "local",
    "allow_environment_variables": "true",
    "_comment_ai": "=== AI Services ===",
    "AIMULTISERVICES_ENDPOINT": "https://<ai-service-name>.cognitiveservices.azure.com/",
    "_comment_openai": "=== Azure OpenAI ===",
    "OPENAI_API_BASE": "https://<openai-resource-name>.openai.azure.com/",
    "_comment_cosmos": "=== Cosmos DB ===",
    "COSMOS_DB_URI": "https://<cosmos-account-name>.documents.azure.com:443/"
  }
}
```
**Why:** Ensures no secrets leak into source control while standardizing required values.

### Local vs Cloud Behavior
- `FUNCTIONAPP_ENV` drives everything. Set it to `local` for development; deployments can omit it (defaults to `cloud`).
- Local mode uses CLI/Azure Developer CLI tokens or explicit keys. Managed Identity calls are intentionally suppressed to avoid IMDS failures.
- Cloud mode keeps the previous behavior: `DefaultAzureCredential` prefers Managed Identity, App Configuration remains available, and key values can stay blank.
- All helper modules share a single credential instance created in `configuration.py`, so switching modes requires no code edits—just environment settings.

### Preparing a Fresh Clone
1. **Install tooling (once per machine)**
   - Python 3.10+ (confirm with `python --version`).
   - Azure Functions Core Tools v4 (`func --version`).
   - Azure CLI (plus Azure Developer CLI if you plan to use `azd`).  
   - PowerShell 7+ for the helper scripts (already standard on the repo path).
2. **Initialize local settings**
   - Copy `pipeline/local.settings.template.json` → `pipeline/local.settings.json`.
   - Fill placeholders for storage endpoints, Document Intelligence, OpenAI, and Cosmos. Use keys only if allowed; otherwise leave them blank to use AAD tokens.
   - Set `FUNCTIONAPP_ENV` to `local` and `allow_environment_variables` to `true`. Leave `APP_CONFIGURATION_URI` empty unless you intentionally want remote config.
3. **Choose an authentication strategy**
   - **Option A (recommended):** `az login --tenant <resource-tenant> --scope https://storage.azure.com//.default` so `DefaultAzureCredential` can use your CLI session.
   - **Option B:** Provide `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` in `local.settings.json` for a dedicated service principal.
   - **Option C:** Use resource keys (fetched via `fetchAzureKeys.ps1`) where policies allow.
4. **Grant RBAC in Azure**
   - Storage: assign `Storage Blob Data Contributor`, `Storage Queue Data Contributor`, and `Storage Table Data Contributor` to your identity on `st257iuu2dpueek`. Needed because Durable Functions relies on queues/tables even if you only read blobs.
   - Cosmos DB: grant `Cosmos DB Built-in Data Contributor` (or equivalent) so token auth succeeds.
   - Document Intelligence & Azure OpenAI: either store keys in `local.settings.json` or grant `Cognitive Services User`/`Cognitive Services OpenAI User` roles.
5. **(Optional) Fetch keys quickly**
   - Run `pwsh .\scripts\fetchAzureKeys.ps1` and paste results into `pipeline/local.settings.json` when temporary key usage is acceptable.

### Running & Testing Locally
1. `pwsh .\scripts\startLocal.ps1` from the repo root.
2. Wait for the script to report the working directory, tool checks, venv creation, and dependency install.
3. Confirm that all eight functions load in the host output and that no `Azure.Identity` errors remain.
4. Exercise the HTTP trigger:  
   ```powershell
   $body = @{
       blobs = @(
           @{
               name      = "bronze/test.pdf"
               url       = "https://<storage-account>.blob.core.windows.net/bronze/test.pdf"
               container = "bronze"
           }
       )
   } | ConvertTo-Json

   $response = Invoke-RestMethod -Uri "http://localhost:7071/api/client" -Method POST -Body $body -ContentType "application/json"
   Invoke-RestMethod -Uri $response.statusQueryGetUri
   ```
5. Set breakpoints in VS Code if needed—the script launches the host in the same session so debugging works out of the box.

### Troubleshooting Quick Reference
- **`invalid_grant` / wrong tenant**: a credential source (CLI, azd, VS) is logged into another tenant. Re-authenticate with the correct tenant or provide service principal credentials.
- **403 on Storage queues/tables**: assign Queue/Table Data Contributor roles and wait a few minutes for propagation.
- **Cosmos `AuthorizationFailure`**: either grant the proper role or provide `COSMOS_DB_KEY` for local mode.
- **App Configuration SSL errors**: leave `APP_CONFIGURATION_URI` blank and ensure `allow_environment_variables=true` so the runtime skips remote configuration.
- **Managed Identity timeouts locally**: expected. Local mode excludes Managed Identity; verify `FUNCTIONAPP_ENV=local` to avoid IMDS calls.

### Appendix: Required `local.settings.json` Keys
- `FUNCTIONS_WORKER_RUNTIME=python`
- `FUNCTIONAPP_ENV=local`
- Optional secrets: `DataStorage`, `AIMULTISERVICES_KEY`, `OPENAI_API_KEY`, `COSMOS_DB_KEY`
- Tokens/endpoints: `DATA_STORAGE_ENDPOINT`, `AIMULTISERVICES_ENDPOINT`, `OPENAI_API_BASE`, `COSMOS_DB_URI`
- Helper flags: `allow_environment_variables=true`, `AzureAppConfigurationDisable=true`, `AzureWebJobsSecretStorageType=Files`

Following this playbook recreates the exact environment we validated: local runs stay self-contained while the same codebase keeps working with Managed Identity and App Configuration once deployed.

