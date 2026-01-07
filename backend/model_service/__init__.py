"""Model service for bird detection.

This package provides an abstraction layer for bird detection models,
allowing the system to support multiple models through a unified interface.
"""

from .base_model import BirdDetectionModel
from .model_factory import ModelType, create_model, get_model_type_from_settings
from .model_loader import BirdNetModel, ModelLoader

__all__ = [
    'BirdDetectionModel',
    'ModelType',
    'create_model',
    'get_model_type_from_settings',
    'BirdNetModel',
    'ModelLoader',  # Backwards compatibility alias
]
