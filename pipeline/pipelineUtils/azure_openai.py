from openai import AzureOpenAI
import logging

from pipelineUtils.db import save_chat_message
from configuration import Configuration
config = Configuration()

openai_config = config.get_openai_config()
OPENAI_API_BASE = openai_config["endpoint"]
OPENAI_API_KEY = openai_config.get("key")
OPENAI_MODEL = openai_config["model"]
OPENAI_API_VERSION = openai_config["api_version"]
OPENAI_API_EMBEDDING_MODEL = openai_config["embedding_model"]


def _create_openai_client():
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


def get_embeddings(text):
    client = _create_openai_client()
    embedding = client.embeddings.create(
        input=text,
        model=OPENAI_API_EMBEDDING_MODEL
    ).data[0].embedding
    
    return embedding


def run_prompt(pipeline_id, system_prompt, user_prompt):
    client = _create_openai_client()

    logging.info(f"User Prompt: {user_prompt}")
    logging.info(f"System Prompt: {system_prompt}")

    save_chat_message(pipeline_id, "system", system_prompt)
    save_chat_message(pipeline_id, "user", user_prompt)

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{ "role": "system", "content": system_prompt},
                {"role":"user","content":user_prompt}])
        assistant_msg = response.choices[0].message.content
        usage = {
            "prompt_tokens":   response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens":    response.usage.total_tokens,
            "model":           response.model
        }

        # 2) log the assistant’s response + usage
        save_chat_message(pipeline_id, "assistant", assistant_msg, usage)
        return assistant_msg
    
    except Exception as e:
        logging.error(f"Error calling OpenAI API: {e}")
        return None


