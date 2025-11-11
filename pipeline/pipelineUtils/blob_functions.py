import logging
from dataclasses import dataclass
import json

from azure.storage.blob import BlobServiceClient

from configuration import Configuration
config = Configuration()

storage_config = config.get_storage_config()
storage_connection = storage_config.get("connection_string")
storage_endpoint = storage_config.get("endpoint")

blob_service_client = None

# Prefer connection string when available (works for Azurite and shared-key scenarios)
if storage_connection:
    try:
        blob_service_client = BlobServiceClient.from_connection_string(storage_connection)
        logging.info("Initialized BlobServiceClient using connection string.")
    except Exception as ex:
        logging.warning(f"Failed to create BlobServiceClient from connection string: {ex}")

# Fall back to managed identity / CLI credentials (requires HTTPS endpoint)
if blob_service_client is None:
    if not storage_endpoint:
        raise ValueError("Storage endpoint not configured. Ensure DATA_STORAGE_ENDPOINT is set.")
    if storage_endpoint.startswith("http://"):
        raise ValueError(
            "Storage endpoint uses HTTP. Provide a connection string (DataStorage) or switch to HTTPS to use token credentials."
        )
    blob_service_client = BlobServiceClient(account_url=storage_endpoint, credential=config.credential)
    logging.info("Initialized BlobServiceClient using endpoint and credential.")

@dataclass
class BlobMetadata:
    name: str
    url: str
    container: str

    def to_dict(self):
        return {"name": self.name, "url": self.url, "container": self.container}

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False)
    

def write_to_blob(container_name, blob_path, data):

    blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_path)
    blob_client.upload_blob(data, overwrite=True)
    return True

def get_blob_content(container_name, blob_path):

    blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_path)
    # Download the blob content
    blob_content = blob_client.download_blob().readall()
    return blob_content

def list_blobs(container_name):
    container_client = blob_service_client.get_container_client(container_name)
    blob_list = container_client.list_blobs()
    return blob_list

def delete_all_blobs_in_container(container_name):
    container_client = blob_service_client.get_container_client(container_name)
    blob_list = container_client.list_blobs()
    for blob in blob_list:
        blob_client = container_client.get_blob_client(blob.name)
        blob_client.delete_blob()