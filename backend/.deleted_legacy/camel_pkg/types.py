"""
Camel Types Compatibility Layer
Directly defines types without importing from parent
"""


class ModelPlatformType:
    """Compatibility with camel.types.ModelPlatformType"""
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"


class ModelType:
    """Compatibility with camel.types.ModelType"""
    # This is just a pass-through - we use whatever model name is provided
    pass
