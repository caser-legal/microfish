"""
Local LLM Client - Uses your endpoint directly
NO camel-ai, NO oasis-ai dependencies
"""

import json
import re
import os
from typing import Optional, Dict, Any, List
from openai import OpenAI


class LocalLLMClient:
    """Direct LLM client using local endpoint"""
    
    def __init__(
        self,
        api_key: str = None,
        base_url: str = None,
        model: str = None
    ):
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self.base_url = base_url or os.environ.get("LLM_BASE_URL", "http://localhost:20128/v1")
        self.model = model or os.environ.get("LLM_MODEL_NAME", "coder")
        
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
        Send chat request.

        max_tokens defaults to None, meaning no limit is sent. Capping it
        truncates long structured output mid-JSON, which surfaces to the caller
        as an unparseable response rather than as the truncation it is.
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

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
                f"finish_reason={choice.finish_reason})"
            )

        # Remove thinking content if present
        content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()

        if choice.finish_reason == 'length':
            raise ValueError(
                f"LLM output was truncated by the max_tokens limit "
                f"(max_tokens={max_tokens}). Raise or remove it for this call."
            )

        return content
    
    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """Send chat request and return JSON"""
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
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON returned by LLM: {cleaned_response}")


# Global client instance
_llm_client: Optional[LocalLLMClient] = None


def get_llm_client() -> LocalLLMClient:
    """Get global LLM client instance"""
    global _llm_client
    if _llm_client is None:
        _llm_client = LocalLLMClient()
    return _llm_client
