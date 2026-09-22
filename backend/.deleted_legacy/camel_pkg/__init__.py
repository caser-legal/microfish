"""
Camel Compatibility Package
NO external dependencies - pure local implementation
"""

from .models import ModelFactory
from .types import ModelPlatformType, ModelType

__all__ = [
    "ModelFactory",
    "ModelPlatformType", 
    "ModelType",
]
