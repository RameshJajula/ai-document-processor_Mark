import os
import logging
from azure.identity import DefaultAzureCredential
from azure.appconfiguration.provider import (
    AzureAppConfigurationKeyVaultOptions,
    load
)
import logging


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
azure_id_logger = logging.getLogger("azure.identity")
azure_id_logger.setLevel(logging.DEBUG)

from tenacity import retry, wait_random_exponential, stop_after_attempt, RetryError

class Configuration:

    credential = None

    def __init__(self):
        logger.info("Configuration initialization started")
        
        # Determine runtime mode: 'local' or 'cloud'
        self.env_mode = os.environ.get('FUNCTIONAPP_ENV', 'cloud').lower()
        logger.info(f"🚀 FUNCTIONAPP_ENV mode: {self.env_mode}")
        
        try:
            self.tenant_id = os.environ.get('AZURE_TENANT_ID', "*")
        except Exception as e:
            raise e
        
        # Configure credentials based on mode
        if self.env_mode == 'local' or os.environ.get("AZURE_FUNCTIONS_ENVIRONMENT") == "Development":
            logger.info("🔧 Using LOCAL mode credentials (CLI/Developer)")
            self.credential = DefaultAzureCredential(
                additionally_allowed_tenants=self.tenant_id,
                exclude_environment_credential=True, 
                exclude_managed_identity_credential=True,
                exclude_cli_credential=False,
                exclude_powershell_credential=True,
                exclude_shared_token_cache_credential=True,
                exclude_developer_cli_credential=False,
                exclude_interactive_browser_credential=True
            )
        else:
            logger.info("☁️ Using CLOUD mode credentials (Managed Identity)")
            self.credential = DefaultAzureCredential(
                additionally_allowed_tenants=self.tenant_id,
                exclude_environment_credential=True, 
                exclude_managed_identity_credential=False,
                exclude_cli_credential=True,
                exclude_powershell_credential=True,
                exclude_shared_token_cache_credential=True,
                exclude_developer_cli_credential=True,
                exclude_interactive_browser_credential=True
            )

        logger.info(f"Using DefaultAzureCredential with tenant ID: {self.tenant_id}")

        # In local mode, skip App Configuration if allow_environment_variables is set
        self.config = None
        if self.env_mode == 'local' and os.environ.get("allow_environment_variables", "false").lower() == "true":
            logger.info("📝 LOCAL mode: Using environment variables only (skipping App Configuration)")
            self.config = None
        else:
            # Try to load from Azure App Configuration
            try:
                logger.info("Attempting APP_CONFIGURATION_URI for configuration.")
                app_config_uri = os.environ.get('APP_CONFIGURATION_URI')
                if app_config_uri:
                    logger.info(f"Using APP_CONFIGURATION_URI: {app_config_uri}")
                    self.config = load(endpoint=app_config_uri, credential=self.credential,key_vault_options=AzureAppConfigurationKeyVaultOptions(credential=self.credential))
                else:
                    raise KeyError("APP_CONFIGURATION_URI not set")
            except Exception as e:
                try:
                    connection_string = os.environ.get("AZURE_APPCONFIG_CONNECTION_STRING")
                    if connection_string:
                        logger.info(f"Using AZURE_APPCONFIG_CONNECTION_STRING for configuration")
                        self.config = load(
                            connection_string=connection_string, 
                            key_vault_options=AzureAppConfigurationKeyVaultOptions(credential=self.credential)
                        )
                    else:
                        if self.env_mode == 'local':
                            logger.warning("⚠️ App Configuration not available. Using environment variables only. Set allow_environment_variables=true")
                        else:
                            raise Exception("Unable to connect to Azure App Configuration. Please check your connection string or endpoint. Error: " + str(e))
                except Exception as e:
                    if self.env_mode == 'local':
                        logger.warning(f"⚠️ App Configuration connection failed. Falling back to environment variables: {e}")
                    else:
                        raise Exception("Unable to connect to Azure App Configuration. Please check your connection string or endpoint. Error: " + str(e))

    # Connect to Azure App Configuration.

    def get_value(self, key: str, default: str = None) -> str:
        
        if key is None:
            raise Exception('The key parameter is required for get_value().')

        value = None

        # In local mode, prioritize environment variables
        allow_env_vars = self.env_mode == 'local' or os.environ.get("allow_environment_variables", "false").lower() == "true"

        if allow_env_vars:
            value = os.environ.get(key)
            if value:
                logger.debug(f"📝 Got '{key}' from environment variable")

        # If not found in env vars and App Config is available, try there
        if value is None and self.config is not None:
            try:
                value = self.get_config_with_retry(name=key)
                if value:
                    logger.debug(f"☁️ Got '{key}' from App Configuration")
            except Exception as e:
                logger.debug(f"Could not get '{key}' from App Configuration: {e}")

        if value is not None:
            return value
        else:
            if default is not None:
                logger.debug(f"⚙️ Using default value for '{key}'")
                return default
            
            raise Exception(f'The configuration variable {key} not found in environment or App Configuration.')
    
    def try_get_value(self, key: str):
        """Best-effort retrieval that returns None instead of raising when missing."""
        sentinel = "__CONFIG_OPTIONAL_MISSING__"
        value = self.get_value(key, sentinel)
        return None if value == sentinel else value
        
    def retry_before_sleep(self, retry_state):
        # Log the outcome of each retry attempt.
        message = f"""Retrying {retry_state.fn}:
                        attempt {retry_state.attempt_number}
                        ended with: {retry_state.outcome}"""
        if retry_state.outcome.failed:
            ex = retry_state.outcome.exception()
            message += f"; Exception: {ex.__class__.__name__}: {ex}"
        if retry_state.attempt_number < 1:
            logging.info(message)
        else:
            logging.warning(message)

    @retry(
        wait=wait_random_exponential(multiplier=1, max=5),
        stop=stop_after_attempt(5),
        before_sleep=retry_before_sleep
    )
    def get_config_with_retry(self, name):
        try:
            return self.config[name]
        except RetryError:
            pass

    # Helper functions for reading environment variables
    def read_env_variable(self, var_name, default=None):
        value = self.get_value(var_name, default)
        return value.strip() if value else default

    def read_env_list(self, var_name):
        value = self.get_value(var_name, "")
        return [item.strip() for item in value.split(",") if item.strip()]

    def read_env_boolean(self, var_name, default=False):
        value = self.get_value(var_name, str(default)).strip().lower()
        return value in ['true', '1', 'yes']
    
    # Helper methods for service-specific configurations
    def is_local_mode(self) -> bool:
        """Check if running in local development mode."""
        return self.env_mode == 'local'
    
    def get_storage_config(self) -> dict:
        """Get storage account configuration."""
        return {
            'endpoint': self.get_value('DATA_STORAGE_ENDPOINT'),
            'connection_string': self.try_get_value('DataStorage')
        }
    
    def get_document_intelligence_config(self) -> dict:
        """Get Document Intelligence service configuration."""
        return {
            'endpoint': self.get_value('AIMULTISERVICES_ENDPOINT'),
            'key': self.try_get_value('AIMULTISERVICES_KEY')
        }
    
    def get_openai_config(self) -> dict:
        """Get Azure OpenAI configuration."""
        return {
            'endpoint': self.get_value('OPENAI_API_BASE'),
            'key': self.try_get_value('OPENAI_API_KEY'),
            'model': self.get_value('OPENAI_MODEL'),
            'api_version': self.get_value('OPENAI_API_VERSION'),
            'embedding_model': self.get_value('OPENAI_API_EMBEDDING_MODEL', 'text-embedding-ada-002')
        }
    
    # Start: RJ_AI_DOC_Update (Cosmos configuration helpers)
    def get_cosmos_config(self) -> dict:
        """Get Cosmos DB configuration."""
        return {
            'uri': self.get_value('COSMOS_DB_URI'),
            'key': self.try_get_value('COSMOS_DB_KEY'),
            'database': self.get_value('COSMOS_DB_DATABASE_NAME'),
            'container': self.get_value('COSMOS_DB_CONVERSATION_CONTAINER')
        }

    def get_prompts_cosmos_config(self) -> dict:
        """Get Cosmos settings for prompt storage, falling back to conversation container."""
        database = self.try_get_value('PROMPTS_COSMOS_DATABASE') or self.get_value('COSMOS_DB_DATABASE_NAME')
        container = self.try_get_value('PROMPTS_COSMOS_CONTAINER') or self.get_value('COSMOS_DB_CONVERSATION_CONTAINER')
        partition_value = self.try_get_value('PROMPTS_COSMOS_PARTITION_KEY_VALUE')
        return {
            'database': database,
            'container': container,
            'partition_key_value': partition_value
        }

    def get_prompts_cosmos_document_id(self) -> str:
        """Document id to retrieve when PROMPT_FILE is set to COSMOS."""
        document_id = self.try_get_value('PROMPTS_COSMOS_DOCUMENT_ID')
        if not document_id:
            raise Exception("PROMPTS_COSMOS_DOCUMENT_ID must be set when PROMPT_FILE is 'COSMOS'.")
        return document_id
    # End: RJ_AI_DOC_Update (Cosmos configuration helpers)

    def get_api_key(self) -> str | None:
        """API key used for authenticating HTTP requests (optional)."""
        return self.try_get_value('API_KEY')