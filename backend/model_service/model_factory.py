"""Model factory for creating bird detection model and location filter instances.

This module provides a factory pattern for instantiating bird detection models
and location filters based on configuration. It allows the system to support
multiple model types (BirdNET, Perch, etc.) through a unified interface.
"""

import logging
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
        )

    if model_type == ModelType.BIRDNET_V3:
        from config import settings

        from .birdnet_v3_model import BirdNetV3Model
        return BirdNetV3Model(
            model_path=settings.MODEL_V3_PATH,
            labels_path=settings.LABELS_V3_PATH,
            manifest_path=settings.MODEL_V3_MANIFEST_PATH,
        )

    raise ValueError(f"Unknown model type: {model_type}")


def create_location_filter(
    model_type: ModelType,
    model: "BirdDetectionModel | None" = None,
    birdnet_labels: "list[str] | None" = None,
) -> "LocationFilter":
    """Factory to create a ready-to-use location filter.

    Owns load and fallback logic: loads the filter internally, and falls
    back to a degraded NoFilter on failure so acoustic inference stays available.

    Args:
        model_type: The active model type.
        model: The loaded BirdDetectionModel (needed for V2.4 ModelBackedFilter).
        birdnet_labels: Labels from the loaded model (needed for GeoModelFilter
            cross-referencing). If None, calls model.get_labels().

    Returns:
        A loaded LocationFilter instance, ready to use.
    """
    from .geomodel_assets import GeoModelAssetError
    from .location_filter import GeoModelFilter, ModelBackedFilter, NoFilter

    unavailable_message = (
        "Location filtering failed to start. Acoustic detections are continuing "
        "without location filtering; check System Logs for details."
    )

    if model_type == ModelType.BIRDNET:
        if model is None:
            logger.error(
                "V2.4 location filter requires a loaded model; location filtering disabled"
            )
            return NoFilter.degraded(
                code="location_model_missing",
                message=unavailable_message,
            )
        try:
            model_filter = ModelBackedFilter(model)
            model_filter.load()
            return model_filter
        except Exception as exc:
            logger.error(
                "V2.4 location meta-model validation failed; location filtering disabled",
                extra={'error': str(exc)},
                exc_info=True,
            )
            return NoFilter.degraded(
                code="meta_model_validation_failed",
                message=unavailable_message,
            )

    if model_type == ModelType.BIRDNET_V3:
        from config import settings

        labels = birdnet_labels if birdnet_labels is not None else (
            model.get_labels() if model is not None else []
        )

        try:
            geo_filter = GeoModelFilter(
                model_path=settings.GEOMODEL_PATH,
                labels_path=settings.GEOMODEL_LABELS_PATH,
                manifest_path=settings.GEOMODEL_MANIFEST_PATH,
                birdnet_labels=labels,
            )
            geo_filter.load()
            return geo_filter
        except GeoModelAssetError as exc:
            logger.error(
                "Geomodel validation failed, location filtering disabled",
                extra={'error': str(exc)},
                exc_info=True,
            )
            return NoFilter.degraded(
                code="geomodel_validation_failed",
                message=unavailable_message,
            )
        except Exception as exc:
            logger.error(
                "Unexpected geomodel load failure, location filtering disabled",
                extra={'error': str(exc)},
                exc_info=True,
            )
            return NoFilter.degraded(
                code="geomodel_load_failed",
                message=unavailable_message,
            )

    logger.error(f"No location filter for model type '{model_type}', using NoFilter")
    return NoFilter.degraded(
        code="location_filter_unsupported",
        message=unavailable_message,
    )


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
