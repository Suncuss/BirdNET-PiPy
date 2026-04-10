"""Model factory for creating bird detection model and location filter instances.

This module provides a factory pattern for instantiating bird detection models
and location filters based on configuration. It allows the system to support
multiple model types (BirdNET, Perch, etc.) through a unified interface.
"""

import logging
import os
from typing import TYPE_CHECKING

from config.constants import ModelType

if TYPE_CHECKING:
    from .base_model import BirdDetectionModel
    from .location_filter import LocationFilter

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


def create_location_filter(
    model_type: ModelType,
    model: "BirdDetectionModel | None" = None,
    birdnet_labels: "list[str] | None" = None,
) -> "LocationFilter":
    """Factory to create a ready-to-use location filter.

    Owns load and fallback logic: loads the filter internally, and falls
    back to NoFilter on any failure (logged as a warning).

    Args:
        model_type: The active model type.
        model: The loaded BirdDetectionModel (needed for V2.4 ModelBackedFilter).
        birdnet_labels: Labels from the loaded model (needed for GeoModelFilter
            cross-referencing). If None, calls model.get_labels().

    Returns:
        A loaded LocationFilter instance, ready to use.
    """
    from .location_filter import GeoModelFilter, ModelBackedFilter, NoFilter

    if model_type == ModelType.BIRDNET:
        if model is None:
            logger.warning("V2.4 ModelBackedFilter requires a model instance, falling back to NoFilter")
            return NoFilter()
        return ModelBackedFilter(model)

    if model_type == ModelType.BIRDNET_V3:
        from config import settings

        if not os.path.exists(settings.GEOMODEL_PATH):
            logger.info("Geomodel not found, location filtering disabled", extra={
                'expected_path': settings.GEOMODEL_PATH,
            })
            return NoFilter()

        if not os.path.exists(settings.GEOMODEL_LABELS_PATH):
            logger.warning("Geomodel labels not found, location filtering disabled", extra={
                'expected_path': settings.GEOMODEL_LABELS_PATH,
            })
            return NoFilter()

        labels = birdnet_labels if birdnet_labels is not None else (
            model.get_labels() if model is not None else []
        )

        try:
            geo_filter = GeoModelFilter(
                model_path=settings.GEOMODEL_PATH,
                labels_path=settings.GEOMODEL_LABELS_PATH,
                birdnet_labels=labels,
            )
            geo_filter.load()
            return geo_filter
        except Exception:
            logger.warning("Failed to load geomodel, location filtering disabled", exc_info=True)
            return NoFilter()

    logger.warning(f"No location filter for model type '{model_type}', using NoFilter")
    return NoFilter()


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
