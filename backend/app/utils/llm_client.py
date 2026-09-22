"""
LLM Client Wrapper
Unified OpenAI format for API calls
"""

import json
import re
from typing import Optional, Dict, Any, List
from openai import OpenAI

from ..config import Config


class LLMClient:
    """LLM Client"""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model = model or Config.LLM_MODEL_NAME
        
        if not self.api_key:
            raise ValueError("LLM_API_KEY not configured")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict] = None
    ) -> str:
        """
        Send chat request

        Args:
            messages: Message list
            temperature: Temperature parameter
            max_tokens: Maximum token count. Pass None (the default) to omit the
                limit entirely and let the model generate as much as it needs.
            response_format: Response format (e.g., JSON mode)

        Returns:
            Model response text
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        # Only send max_tokens when a limit was explicitly requested. Capping this
        # truncates long structured output (e.g. the ontology) mid-JSON.
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        if response_format:
            kwargs["response_format"] = response_format

        response = self.client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        content = choice.message.content

        if content is None or not content.strip():
            raise ValueError(
                f"LLM returned an empty response (model={self.model}, "
                f"finish_reason={choice.finish_reason}). Check that the model name "
                f"is valid at {self.base_url} and that the endpoint is reachable."
            )

        # Some models (like MiniMax M2.5) may include <think> thinking content, need to remove it
        content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()

        # Surface truncation explicitly. Without this the caller only sees a JSON
        # parse failure and blames the model or the API key.
        if choice.finish_reason == 'length':
            raise ValueError(
                f"LLM output was truncated by the max_tokens limit "
                f"(max_tokens={max_tokens}, model={self.model}). The response is "
                f"incomplete. Raise or remove max_tokens for this call."
            )

        return content
    
    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Send chat request and return JSON

        Args:
            messages: Message list
            temperature: Temperature parameter
            max_tokens: Maximum token count. Pass None (the default) to let the
                model generate the full structure without truncation.

        Returns:
            Parsed JSON object
        """
        response = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"}
        )
        # Clean up markdown code block markers
        cleaned_response = response.strip()
        cleaned_response = re.sub(r'^```(?:json)?\s*\n?', '', cleaned_response, flags=re.IGNORECASE)
        cleaned_response = re.sub(r'\n?```\s*$', '', cleaned_response)
        cleaned_response = cleaned_response.strip()

        try:
            return json.loads(cleaned_response)
        except json.JSONDecodeError as e:
            preview = cleaned_response[:500]
            suffix = "..." if len(cleaned_response) > 500 else ""
            raise ValueError(
                f"Invalid JSON returned by LLM ({e}). "
                f"Received {len(cleaned_response)} characters. Preview: {preview}{suffix}"
            )


