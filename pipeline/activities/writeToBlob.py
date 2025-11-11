import azure.durable_functions as df
import logging
from pipelineUtils.blob_functions import list_blobs, get_blob_content, write_to_blob
import os

from configuration import Configuration
config = Configuration()

NEXT_STAGE = config.get_value("NEXT_STAGE")
logging.info(f"writeToBlob.py: NEXT_STAGE is {NEXT_STAGE}")
name = "writeToBlob"
bp = df.Blueprint()

@bp.function_name(name)
@bp.activity_trigger(input_name="args")
def extract_text_from_blob(args: dict):
  """
  Writes the JSON bytes to a blob storage.
  Args:
      args (dict): A dictionary containing the blob name and JSON bytes.
  """
  try:
      json_str = args.get('json_str')
      if not isinstance(json_str, str) or not json_str.strip():
          raise ValueError("writeToBlob requires 'json_str' to be a non-empty string.")

      args['json_bytes'] = args['json_str'].encode('utf-8')

      sourcefile = os.path.splitext(os.path.basename(args['blob_name']))[0]
      # Start: RJ_AI_DOC_Update - per-instance output isolation
      output_blob = f"{args.get('instance_id', 'general')}/{sourcefile}-output.json"
      logging.info(f"writeToBlob.py: Writing output to blob {output_blob} (source file {sourcefile}, NEXT_STAGE {NEXT_STAGE})")
      result = write_to_blob(NEXT_STAGE, output_blob, args['json_bytes'])
      # End: RJ_AI_DOC_Update - per-instance output isolation
      logging.info(f"writeToBlob.py: Result of write_to_blob: {result}")
      if result:
          logging.info(f"writeToBlob.py: Successfully wrote output to blob {args['blob_name']}")
          return {
              "success": True,
              "blob_name": args['blob_name'],
              "output_blob": output_blob
          }
      else:
          logging.error(f"Failed to write output to blob {args['blob_name']}")
          return {
              "success": False,
              "error": "Failed to write output"
          }
  except Exception as e:
      error_msg = f"Error writing output for blob {args['blob_name']}: {str(e)}"
      logging.error(error_msg)
      return {
          "success": False,
          "error": error_msg
      }
