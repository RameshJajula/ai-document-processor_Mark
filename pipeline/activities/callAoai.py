import azure.durable_functions as df

import logging
import os
from pipelineUtils.prompts import load_prompts
from pipelineUtils.blob_functions import get_blob_content, write_to_blob
from pipelineUtils.azure_openai import run_prompt
import json

name = "callAoai"
bp = df.Blueprint()

# Start: RJ_AI_DOC_Update (OpenAI call validation & parsing)
@bp.function_name(name)
@bp.activity_trigger(input_name="inputData")
def run(inputData: dict):
    """
    Calls the Azure OpenAI service with the provided text result.

    Args:
        inputData (dict): expects keys 'text_result' and 'instance_id'.

    Returns:
        str: JSON string returned from OpenAI or None on failure.
    """
    instance_id = inputData.get('instance_id') if isinstance(inputData, dict) else None

    try:
        if not isinstance(inputData, dict):
            raise TypeError(f"callAoai expected dict input; received {type(inputData)}")

        text_result = inputData.get('text_result')
        if not text_result:
            raise ValueError("callAoai requires 'text_result' to be a non-empty string.")

        prompt_json = load_prompts()
        system_prompt = prompt_json.get('system_prompt')
        user_prompt_template = prompt_json.get('user_prompt')

        if not system_prompt or not user_prompt_template:
            raise KeyError("Prompt configuration must include 'system_prompt' and 'user_prompt'.")

        full_user_prompt = f"{user_prompt_template.rstrip()}\n\n{text_result}"
        logging.info(f"[callAoai] Sending prompt for instance {instance_id}")
        response_content = run_prompt(instance_id, system_prompt, full_user_prompt)

        if response_content is None:
            raise RuntimeError("Azure OpenAI returned no content.")

        trimmed = response_content.strip()
        if trimmed.startswith("```"):
            logging.debug("[callAoai] Detected fenced response, attempting to unwrap")
            # Remove leading and trailing fences like ```json ... ```
            trimmed = trimmed.strip("`")
            if trimmed.lower().startswith("json"):
                trimmed = trimmed[4:].strip()

        # Ensure response is valid JSON to avoid writing malformed content
        try:
            parsed = json.loads(trimmed)
            json_str = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        except json.JSONDecodeError:
            logging.warning("[callAoai] OpenAI response is not valid JSON; returning raw content.")
            json_str = trimmed

        return json_str

    except Exception as e:
        logging.error(f"[callAoai] Error processing instance {instance_id}: {e}", exc_info=True)
        return None
# End: RJ_AI_DOC_Update (OpenAI call validation & parsing)