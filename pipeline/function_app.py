import azure.functions as func
import azure.durable_functions as df

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeResult, AnalyzeDocumentRequest

from activities import getBlobContent, runDocIntel, callAoai, writeToBlob
from configuration import Configuration

from pipelineUtils.prompts import load_prompts
from pipelineUtils.blob_functions import get_blob_content, write_to_blob, BlobMetadata
from pipelineUtils.azure_openai import run_prompt
from azure.durable_functions import RetryOptions

config = Configuration()

NEXT_STAGE = config.get_value("NEXT_STAGE")
API_KEY = config.get_api_key()

app = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS)

import asyncio
import json
import logging
import math
import time
import uuid
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Dict

# Start: RJ_AI_DOC_Update (Telemetry/Auth scaffolding)
if API_KEY:
    logging.info("API key authentication enabled.")
else:
    logging.warning("API key not configured; HTTP endpoints are open.")

# Blob-triggered starter
@app.function_name(name="start_orchestrator_on_blob")
@app.blob_trigger(
    arg_name="blob",
    path="bronze/{name}",
    connection="DataStorage",
)
@app.durable_client_input(client_name="client")
async def start_orchestrator_blob(
    blob: func.InputStream,
    client: df.DurableOrchestrationClient,
):
    logging.info(f"Blob Received: {blob}") 
    logging.info(f"path: {blob.name}")
    logging.info(f"Size: {blob.length} bytes")
    logging.info(f"URI: {blob.uri}")   

    blob_metadata = BlobMetadata(
        name=blob.name,          # e.g. 'bronze/file.txt'
        url=blob.uri,            # full blob URL
        container="bronze",
    )
    logging.info(f"Blob Metadata: {blob_metadata}")
    logging.info(f"Blob Metadata JSON: {blob_metadata.to_dict()}")
    instance_id = await client.start_new("orchestrator", client_input=[blob_metadata.to_dict()])
    logging.info(f"Started orchestration {instance_id} for blob {blob.name}")


def _json_response(success: bool, message: str, status_code: int, correlation_id: str, data: Dict[str, Any] | None = None) -> func.HttpResponse:
  payload: Dict[str, Any] = {
      "success": success,
      "message": message,
      "correlationId": correlation_id
  }
  if data:
      payload["data"] = data

  return func.HttpResponse(
      json.dumps(payload),
      status_code=status_code,
      mimetype="application/json"
  )


def _track_event(event_name: str, correlation_id: str | None = None, instance_id: str | None = None, **kwargs):
  custom_dimensions: Dict[str, Any] = {"event": event_name}
  if correlation_id:
      custom_dimensions["correlationId"] = correlation_id
  if instance_id:
      custom_dimensions["instanceId"] = instance_id
  custom_dimensions.update(kwargs)
  logging.info(event_name, extra={"custom_dimensions": custom_dimensions})
# End: RJ_AI_DOC_Update (Telemetry/Auth scaffolding)


# Start: RJ_AI_DOC_Update (Auth & rate limiting helpers)
def _authenticate_request(req: func.HttpRequest, correlation_id: str):
  if API_KEY is None:
      return True, None

  supplied_key = (
      req.headers.get("x-api-key")
      or req.headers.get("X-API-Key")
      or req.params.get("code")
  )
  if supplied_key is not None:
      supplied_key = supplied_key.strip()

  if supplied_key == API_KEY:
      return True, None

  logging.warning("Unauthorized request (correlationId=%s).", correlation_id)
  return False, _json_response(False, "Unauthorized.", 401, correlation_id)


async def _enforce_rate_limit(lock: asyncio.Lock, hits: deque, limit: int, window_seconds: int):
  async with lock:
      now = time.monotonic()
      while hits and now - hits[0] > window_seconds:
          hits.popleft()

      if len(hits) >= limit:
          retry_after = window_seconds - (now - hits[0])
          return False, max(0, retry_after)

      hits.append(now)
      return True, None
# End: RJ_AI_DOC_Update (Auth & rate limiting helpers)


# An HTTP-triggered function with a Durable Functions client binding
@app.route(route="client")
@app.durable_client_input(client_name="client")
async def start_orchestrator_http(req: func.HttpRequest, client):
  """
  Starts a new orchestration instance and returns a response to the client.

  args:
    req (func.HttpRequest): The HTTP request object. Contains an array of JSONs with fields: name, url, and container
    client (DurableOrchestrationClient): The Durable Functions client.
  response:
    func.HttpResponse: The HTTP response object.
  """
  
  correlation_id = str(uuid.uuid4())

  authorized, auth_response = _authenticate_request(req, correlation_id)
  if not authorized:
      return auth_response

  allowed, retry_after = await _enforce_rate_limit(
      start_orchestrator_http._rate_lock,
      start_orchestrator_http._rate_hits,
      start_orchestrator_http._rate_limit,
      start_orchestrator_http._rate_window_seconds
  )
  if not allowed:
      message = f"Too many requests. Try again in {math.ceil(retry_after)} seconds."
      _track_event("OrchestrationRequestThrottled", correlation_id=correlation_id, retryAfterSeconds=math.ceil(retry_after))
      return _json_response(False, message, 429, correlation_id)

  try:
      body = req.get_json()
  except ValueError:
      logging.warning("[start_orchestrator_http] Invalid JSON payload received.")
      return _json_response(False, "Invalid JSON payload.", 400, correlation_id)

  blobs = body.get("blobs")
  if not isinstance(blobs, list) or not blobs:
      logging.warning("[start_orchestrator_http] Missing or empty 'blobs' array.")
      return _json_response(False, "Invalid request: 'blobs' must be a non-empty array.", 400, correlation_id)

  required = ("name", "url", "container")
  for i, b in enumerate(blobs):
      if not isinstance(b, dict):
          logging.warning("[start_orchestrator_http] blobs[%s] is not an object.", i)
          return _json_response(False, f"Invalid request: blobs[{i}] must be an object.", 400, correlation_id)
      if any(k not in b or not isinstance(b[k], str) or not b[k].strip() for k in required):
          logging.warning("[start_orchestrator_http] blobs[%s] missing required keys.", i)
          return _json_response(
              False,
              f"Invalid request: blobs[{i}] must contain non-empty string keys {required}.",
              400,
              correlation_id
          )
  
  #invoke the orchestrator function with the list of blobs
  instance_id = await client.start_new('orchestrator', client_input=blobs)
  logging.info("Started orchestration %s (correlationId=%s).", instance_id, correlation_id)
  _track_event("OrchestrationStarted", correlation_id=correlation_id, instance_id=instance_id, blobCount=len(blobs))

  status_http = client.create_check_status_response(req, instance_id)
  try:
      status_payload = json.loads(status_http.get_body().decode("utf-8"))
  except Exception:
      status_payload = {}

  data = {
      "instanceId": instance_id,
      "durableStatus": status_payload
  }
  return _json_response(True, "Orchestration started.", 202, correlation_id, data)


start_orchestrator_http._rate_hits = deque()
start_orchestrator_http._rate_lock = asyncio.Lock()
start_orchestrator_http._rate_limit = 20
start_orchestrator_http._rate_window_seconds = 60


@app.route(route="status/{instanceId}", methods=["GET"])
@app.durable_client_input(client_name="client")
async def get_orchestration_status(req: func.HttpRequest, client) -> func.HttpResponse:
  correlation_id = str(uuid.uuid4())
  authorized, auth_response = _authenticate_request(req, correlation_id)
  if not authorized:
      return auth_response

  instance_id = req.route_params.get("instanceId")
  if not instance_id:
      return _json_response(False, "Instance ID is required.", 400, correlation_id)

  show_history = req.params.get("history", "false").lower() == "true"

  try:
      status = await client.get_status(
          instance_id,
          show_history=show_history,
          show_history_output=show_history
      )
  except Exception as exc:
      logging.error("[get_orchestration_status] Failed for %s: %s", instance_id, exc, exc_info=True)
      return _json_response(False, "Failed to retrieve orchestration status.", 500, correlation_id)

  if status is None:
      return _json_response(False, f"Orchestration '{instance_id}' not found.", 404, correlation_id)

  data: Dict[str, Any] = {
      "instanceId": status.instance_id,
      "name": status.name,
      "runtimeStatus": str(status.runtime_status) if status.runtime_status else None,
      "createdTime": status.created_time.isoformat() if status.created_time else None,
      "lastUpdatedTime": status.last_updated_time.isoformat() if status.last_updated_time else None,
      "customStatus": status.custom_status,
      "output": status.output
  }

  if show_history and status.history:
      data["history"] = status.history

  _track_event("OrchestrationStatusRetrieved", correlation_id=correlation_id, instance_id=instance_id, historyReturned=show_history)
  return _json_response(True, "Status retrieved.", 200, correlation_id, data)


@app.route(route="results/{instanceId}", methods=["GET"])
@app.durable_client_input(client_name="client")
async def get_orchestration_results(req: func.HttpRequest, client) -> func.HttpResponse:
  correlation_id = str(uuid.uuid4())
  authorized, auth_response = _authenticate_request(req, correlation_id)
  if not authorized:
      return auth_response

  instance_id = req.route_params.get("instanceId")
  if not instance_id:
      return _json_response(False, "Instance ID is required.", 400, correlation_id)

  try:
      status = await client.get_status(instance_id)
  except Exception as exc:
      logging.error("[get_orchestration_results] Failed for %s: %s", instance_id, exc, exc_info=True)
      return _json_response(False, "Failed to retrieve orchestration output.", 500, correlation_id)

  if status is None:
      return _json_response(False, f"Orchestration '{instance_id}' not found.", 404, correlation_id)

  if status.output is None:
      return _json_response(False, f"Orchestration '{instance_id}' has no output yet.", 404, correlation_id)

  data = {
      "instanceId": instance_id,
      "output": status.output
  }
  _track_event("OrchestrationOutputRetrieved", correlation_id=correlation_id, instance_id=instance_id)
  return _json_response(True, "Output retrieved.", 200, correlation_id, data)


@app.route(route="history", methods=["GET"])
@app.durable_client_input(client_name="client")
async def list_orchestration_history(req: func.HttpRequest, client) -> func.HttpResponse:
  correlation_id = str(uuid.uuid4())
  authorized, auth_response = _authenticate_request(req, correlation_id)
  if not authorized:
      return auth_response

  limit_param = req.params.get("limit")
  try:
      limit = int(limit_param) if limit_param else 20
      limit = max(1, min(limit, 100))
  except ValueError:
      return _json_response(False, "Query parameter 'limit' must be an integer.", 400, correlation_id)

  since_param = req.params.get("since")
  since_time = None
  if since_param:
      try:
          since_time = datetime.fromisoformat(since_param)
      except ValueError:
          return _json_response(False, "Query parameter 'since' must be ISO-8601 (e.g., 2025-11-11T15:00:00).", 400, correlation_id)

  try:
      statuses = await client.get_status_all()
  except Exception as exc:
      logging.error("[list_orchestration_history] Failed: %s", exc, exc_info=True)
      return _json_response(False, "Failed to retrieve orchestration history.", 500, correlation_id)

  if since_time:
      statuses = [
          s for s in statuses
          if s.created_time and s.created_time.replace(tzinfo=None) >= since_time
      ]

  statuses.sort(key=lambda s: s.created_time or datetime.min, reverse=True)
  items: list[Dict[str, Any]] = []
  for status in statuses[:limit]:
      items.append({
          "instanceId": status.instance_id,
          "name": status.name,
          "runtimeStatus": str(status.runtime_status) if status.runtime_status else None,
          "createdTime": status.created_time.isoformat() if status.created_time else None,
          "lastUpdatedTime": status.last_updated_time.isoformat() if status.last_updated_time else None,
          "outputAvailable": status.output is not None
      })

  data = {
      "items": items,
      "continuationToken": None  # Full pagination not supported in this basic listing
  }

  _track_event("OrchestrationHistoryRetrieved", correlation_id=correlation_id, itemCount=len(items))
  return _json_response(True, "History retrieved.", 200, correlation_id, data)

@app.route(route="chat", methods=["POST"])
async def direct_chat(req: func.HttpRequest) -> func.HttpResponse:
  """
  Accepts a query and optional context, invokes Azure OpenAI using the shared
  run_prompt helper, and returns the LLM response as plain text.
  """
  correlation_id = str(uuid.uuid4())
  authorized, auth_response = _authenticate_request(req, correlation_id)
  if not authorized:
      return auth_response

  allowed, retry_after = await _enforce_rate_limit(
      direct_chat._rate_lock,
      direct_chat._rate_hits,
      direct_chat._rate_limit,
      direct_chat._rate_window_seconds
  )
  if not allowed:
      message = f"Too many chat requests. Try again in {math.ceil(retry_after)} seconds."
      _track_event("ChatRequestThrottled", correlation_id=correlation_id, retryAfterSeconds=math.ceil(retry_after))
      return _json_response(False, message, 429, correlation_id)

  try:
      body = req.get_json()
  except ValueError:
      return _json_response(False, "Invalid JSON payload.", 400, correlation_id)

  query = body.get("query")
  context = body.get("context", "")
  pipeline_id = body.get("pipelineId") or f"http-{uuid.uuid4()}"

  if not isinstance(query, str) or not query.strip():
      return _json_response(False, "Invalid request: 'query' must be a non-empty string.", 400, correlation_id)

  system_prompt = (
      "You are a helpful assistant. Use any provided context to answer the user's query.\n"
      f"Context:\n{context}"
  )

  loop = asyncio.get_running_loop()
  result = await loop.run_in_executor(None, lambda: run_prompt(pipeline_id, system_prompt, query.strip()))

  if result is None:
      return _json_response(False, "Failed to generate response from Azure OpenAI.", 502, correlation_id)

  data = {
      "pipelineId": pipeline_id,
      "response": result
  }
  _track_event("ChatResponseGenerated", correlation_id=correlation_id, pipelineId=pipeline_id)
  return _json_response(True, "Response generated.", 200, correlation_id, data)


direct_chat._rate_hits = deque()
direct_chat._rate_lock = asyncio.Lock()
direct_chat._rate_limit = 60
direct_chat._rate_window_seconds = 60

# Orchestrator
@app.function_name(name="orchestrator")
@app.orchestration_trigger(context_name="context")
def run(context):
  input_data = context.get_input()
  logging.info(f"Context {context}")
  logging.info(f"Input data: {input_data}")
  
  sub_tasks = []

  for blob_metadata in input_data:
    logging.info(f"Calling sub orchestrator for blob: {blob_metadata}")
    sub_tasks.append(context.call_sub_orchestrator("ProcessBlob", blob_metadata))

  logging.info(f"Sub tasks: {sub_tasks}")

  # Runs a list of asynchronous tasks in parallel and waits for all of them to complete. In this case, the tasks are sub-orchestrations that process each blob_metadata in parallel
  results = yield context.task_all(sub_tasks)
  logging.info(f"Results: {results}")
  _track_event("OrchestrationCompleted", instance_id=context.instance_id, resultCount=len(results))
  return results

#Sub orchestrator
@app.function_name(name="ProcessBlob")
@app.orchestration_trigger(context_name="context")
def process_blob(context):
  blob_metadata = context.get_input()
  sub_orchestration_id = context.instance_id 
  logging.info(f"Process Blob sub Orchestration - Processing blob_metadata: {blob_metadata} with sub orchestration id: {sub_orchestration_id}")
  # Start: RJ_AI_DOC_Update - Sub-orchestration telemetry & resilience
  parent_id = context.parent_instance_id
  _track_event(
      "ProcessBlobStarted",
      instance_id=sub_orchestration_id,
      parentInstanceId=parent_id,
      blobName=blob_metadata.get("name") if isinstance(blob_metadata, dict) else str(blob_metadata)
  )

  doc_retry = RetryOptions(5, 3)
  doc_retry.backoff_coefficient = 2
  doc_retry.max_retry_interval = timedelta(seconds=30)
  text_result = yield context.call_activity_with_retry("runDocIntel", doc_retry, blob_metadata)

  # Package the data into a dictionary
  call_aoai_input = {
      "text_result": text_result,
      "instance_id": sub_orchestration_id 
  }

  aoai_retry = RetryOptions(10, 3)
  aoai_retry.backoff_coefficient = 2
  aoai_retry.max_retry_interval = timedelta(seconds=60)
  json_str = yield context.call_activity_with_retry("callAoai", aoai_retry, call_aoai_input)
  
  write_retry = RetryOptions(5, 5)
  write_retry.backoff_coefficient = 2
  write_retry.max_retry_interval = timedelta(seconds=30)
  task_result = yield context.call_activity_with_retry(
      "writeToBlob", 
      write_retry,
      {
          "json_str": json_str, 
          "blob_name": blob_metadata["name"],
          "instance_id": context.parent_instance_id or context.instance_id
      }
  )
  result_payload = {
      "blob": blob_metadata,
      "text_result": text_result,
      "task_result": task_result
  }   
  _track_event(
      "ProcessBlobCompleted",
      instance_id=sub_orchestration_id,
      parentInstanceId=parent_id,
      success=task_result.get("success") if isinstance(task_result, dict) else None,
      outputBlob=task_result.get("output_blob") if isinstance(task_result, dict) else None
  )
  return result_payload
  # End: RJ_AI_DOC_Update - Sub-orchestration telemetry & resilience

app.register_functions(getBlobContent.bp)
app.register_functions(runDocIntel.bp)
app.register_functions(callAoai.bp)
app.register_functions(writeToBlob.bp)