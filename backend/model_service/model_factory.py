"""Model factory for creating bird detection model instances.

This module provides a factory pattern for instantiating bird detection models
based on configuration. It allows the system to support multiple model types
(BirdNET, Perch, etc.) through a unified interface.
"""

import logging
from typing import TYPE_CHECKING

from config.constants import ModelType

if TYPE_CHECKING:
    from .base_model import BirdDetectionModel

logger = logging.getLogger(__name__)


def create_model(model_type: ModelType = ModelType.BIRDNET) -> "BirdDetectionModel":
    """Factory to instantiate the configured model.

    Args:
        model_type: The type of model to create

    Returns:
        An instance of BirdDetectionModel

    Raises:
        ValueError: If the model type is not supported
    """
    if model_type == ModelType.BIRDNET:
        from config import settings

        from .birdnet_v2_model import BirdNetModel
        return BirdNetModel(
            model_path=settings.MODEL_PATH,
            meta_model_path=settings.META_MODEL_PATH,
            labels_path=settings.LABELS_PATH,
            ebird_codes_path=settings.EBIRD_CODES_PATH
        )

    if model_type == ModelType.BIRDNET_V3:
        from config import settings

        from .birdnet_v3_model import BirdNetV3Model
        return BirdNetV3Model(
            model_path=settings.MODEL_V3_PATH,
            labels_path=settings.LABELS_V3_PATH,
            ebird_codes_path=settings.EBIRD_CODES_PATH
        )

    raise ValueError(f"Unknown model type: {model_type}")


def get_model_type_from_settings() -> ModelType:
    """Read model type from user settings with fallback.

    Returns:
        ModelType enum value, defaults to BIRDNET if setting is invalid
    """
    from config import settings
    model_name = getattr(settings, 'MODEL_TYPE', 'birdnet')
    try:
        return ModelType(model_name)
    except ValueError:
        logger.warning(f"Unknown model type '{model_name}', falling back to birdnet")
        return ModelType.BIRDNET
