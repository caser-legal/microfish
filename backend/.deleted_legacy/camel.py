"""
Camel Compatibility Layer
Maps camel-ai API to our local LLM client
NO external dependencies - uses llm_client
"""

from typing import Any, Dict, Optional
from llm_client import LocalLLMClient, get_llm_client


class ModelPlatformType:
    """Compatibility with camel.types.ModelPlatformType"""
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"


class ModelType:
    """Compatibility with camel.types.ModelType"""
    # This is just a pass-through - we use whatever model name is provided
    pass


class ModelFactory:
    """
    Compatibility with camel.models.ModelFactory
    
    Original usage:
        ModelFactory.create(
            model_platform=ModelPlatformType.OPENAI,
            model_type=llm_model,
        )
    
    Our implementation returns LocalLLMClient which has same interface
    """
    
    @staticmethod
    def create(
        model_platform: str = None,
        model_type: str = None,
        **kwargs
    ) -> LocalLLMClient:
        """
        Create a model instance
        
        Args:
            model_platform: Ignored (kept for compatibility)
            model_type: Model name (e.g., "coder", "gpt-4o-mini")
            **kwargs: Additional arguments (ignored)
            
        Returns:
            LocalLLMClient instance
        """
        # Get model name from environment or use default
        model_name = model_type or kwargs.get("model_name")
        
        # Create client with optional model override
        client = get_llm_client()
        if model_name:
            client.model = model_name
        
        return client


# Re-export types for compatibility
__all__ = [
    "ModelFactory",
    "ModelPlatformType",
    "ModelType",
]
