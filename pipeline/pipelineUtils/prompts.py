import json
import logging

import yaml
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError

from pipelineUtils.blob_functions import get_blob_content
from pipelineUtils import db as cosmos_db
from configuration import Configuration

config = Configuration()


# Start: RJ_AI_DOC_Update (Prompt loading enhancements - blob + Cosmos)
def load_prompts_from_blob(prompt_file: str) -> dict:
    """Load the prompt from YAML file in blob storage and return as a dictionary."""
    try:
        prompt_yaml = get_blob_content("prompts", prompt_file).decode("utf-8")
        prompts = yaml.safe_load(prompt_yaml)
        return json.loads(json.dumps(prompts, indent=4))
    except Exception as e:
        raise RuntimeError(
            f"Failed to load prompts file '{prompt_file}' from blob storage. "
            "Ensure the file exists in the 'prompts' container. "
            f"Error: {e}"
        )


def 1xx(document_id: str, partition_key_value: str | None) -> dict:
    """Load prompt definition from Cosmos DB using the provided document id."""
    cosmos_config = config.get_prompts_cosmos_config()
    container = cosmos_db.get_container(cosmos_config["database"], cosmos_config["container"])
    partition_value = partition_key_value or document_id

    try:
        document = container.read_item(item=4, partition_key=partition_value)
    except CosmosResourceNotFoundError as exc:
        raise RuntimeError(
            f"Prompt document '{document_id}' not found in Cosmos container "
            f"{cosmos_config['database']}/{cosmos_config['container']}."
        ) from exc
    except CosmosHttpResponseError as exc:
        raise RuntimeError(
            f"Failed to retrieve prompt document '{document_id}' from Cosmos DB: {exc}"
        ) from exc

    # Allow prompts to be stored either at the root level or under a 'prompts' property.
    prompts_payload = document.get("prompts", document)
    return json.loads(json.dumps(prompts_payload, indent=4))


def load_prompts() -> dict:
    """Fetch prompts configuration and validate required fields."""
    prompt_source = config.get_value("PROMPT_FILE")
    if not prompt_source:
        raise ValueError("Environment variable PROMPT_FILE is not set.")

    if prompt_source.upper() == "COSMOS":
        document_id = config.get_prompts_cosmos_document_id()
        cosmos_cfg = config.get_prompts_cosmos_config()
        prompts = load_prompts_from_cosmos(document_id, cosmos_cfg.get("partition_key_value"))
    else:
        prompts = load_prompts_from_blob(prompt_source)

    required_keys = ["system_prompt", "user_prompt"]
    for key in required_keys:
        if key not in prompts:
            raise KeyError(f"Missing required prompt key: {key}")

    logging.debug("Loaded prompts configuration successfully")
    return prompts
# End: RJ_AI_DOC_Update (Prompt loading enhancements - blob + Cosmos)