# backendUtils/db.py
import logging
from azure.cosmos import CosmosClient
from datetime import datetime
import uuid

from configuration import Configuration
config = Configuration()

cosmos_config = config.get_cosmos_config()
COSMOS_DB_URI = cosmos_config["uri"]
COSMOS_DB_DATABASE = cosmos_config["database"]
COSMOS_DB_CONTAINER = cosmos_config["container"]
COSMOS_DB_KEY = cosmos_config.get("key")


def _create_cosmos_client():
    if config.is_local_mode() and COSMOS_DB_KEY:
        logging.info("Initializing CosmosClient with key credential (local mode).")
        return CosmosClient(COSMOS_DB_URI, credential=COSMOS_DB_KEY)
    logging.info("Initializing CosmosClient with DefaultAzureCredential.")
    return CosmosClient(COSMOS_DB_URI, credential=config.credential)


_cosmos_client = _create_cosmos_client()
_cosmos_container = _cosmos_client.get_database_client(COSMOS_DB_DATABASE).get_container_client(COSMOS_DB_CONTAINER)


def save_chat_message(conversation_id: str, role: str, content: str, usage: dict = None):
    item = {
        "id": str(uuid.uuid4()),
        "conversationId": conversation_id,
        "role": role,
        "content": content,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
    if usage:
        item.update({
            "promptTokens": usage.get("prompt_tokens"),
            "completionTokens": usage.get("completion_tokens"),
            "totalTokens": usage.get("total_tokens"),
            "model": usage.get("model")
        })

    return _cosmos_container.create_item(body=item)