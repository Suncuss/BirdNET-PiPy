"""Tests for base model interface and factory pattern."""


import pytest


class TestBaseModelInterface:
    """Test that the abstract base class is properly defined."""

    def test_base_model_is_abstract(self):
        """Test that BirdDetectionModel cannot be instantiated directly."""
        from model_service.base_model import BirdDetectionModel

        with pytest.raises(TypeError):
            BirdDetectionModel()

    def test_base_model_has_abstract_methods(self):
        """Test that BirdDetectionModel defines required abstract methods."""
        from model_service.base_model import BirdDetectionModel

        # Check abstract methods exist
        assert hasattr(BirdDetectionModel, 'name')
        assert hasattr(BirdDetectionModel, 'version')
        assert hasattr(BirdDetectionModel, 'sample_rate')
        assert hasattr(BirdDetectionModel, 'chunk_length_seconds')
        assert hasattr(BirdDetectionModel, 'load')
        assert hasattr(BirdDetectionModel, 'predict')
        assert hasattr(BirdDetectionModel, 'get_labels')

    def test_base_model_has_optional_methods(self):
        """Test that BirdDetectionModel defines optional methods with defaults."""
        from model_service.base_model import BirdDetectionModel

        # These are optional (have default implementations)
        assert hasattr(BirdDetectionModel, 'get_ebird_code')
        assert hasattr(BirdDetectionModel, 'filter_by_location')


class TestBirdNetModelImplementation:
    """Test that BirdNetModel properly implements BirdDetectionModel."""

    def test_birdnet_model_is_subclass(self):
        """Test BirdNetModel inherits from BirdDetectionModel."""
        from model_service.base_model import BirdDetectionModel
        from model_service.birdnet_v2_model import BirdNetModel

        assert issubclass(BirdNetModel, BirdDetectionModel)

    def test_birdnet_model_implements_properties(self):
        """Test BirdNetModel has all required property implementations."""
        from model_service.birdnet_v2_model import BirdNetModel

        # These should be class-level constants for BirdNetModel
        assert BirdNetModel.MODEL_NAME == "birdnet"
        assert BirdNetModel.MODEL_VERSION == "2.4"
        assert BirdNetModel.SAMPLE_RATE == 48000
        assert BirdNetModel.CHUNK_LENGTH_SECONDS == 3.0

    def test_birdnet_model_implements_methods(self):
        """Test BirdNetModel has all required method implementations."""
        from model_service.birdnet_v2_model import BirdNetModel

        # Check method implementations exist
        assert callable(getattr(BirdNetModel, 'load', None))
        assert callable(getattr(BirdNetModel, 'predict', None))
        assert callable(getattr(BirdNetModel, 'get_labels', None))
        assert callable(getattr(BirdNetModel, 'get_ebird_code', None))
        assert callable(getattr(BirdNetModel, 'filter_by_location', None))


class TestModelFactory:
    """Test model factory pattern."""

    def test_model_type_enum(self):
        """Test ModelType enum values."""
        from model_service.model_factory import ModelType

        assert ModelType.BIRDNET.value == "birdnet"

    def test_get_model_type_from_settings_default(self):
        """Test default model type is birdnet."""
        from model_service.model_factory import ModelType, get_model_type_from_settings

        # Default should be birdnet
        model_type = get_model_type_from_settings()
        assert model_type == ModelType.BIRDNET

    def test_create_model_returns_birdnet(self):
        """Test factory creates BirdNetModel for BIRDNET type."""
        from model_service.birdnet_v2_model import BirdNetModel
        from model_service.model_factory import ModelType, create_model

        model = create_model(ModelType.BIRDNET)
        assert isinstance(model, BirdNetModel)

    def test_create_model_invalid_type(self):
        """Test factory raises ValueError for unknown type."""
        from model_service.model_factory import create_model

        # Create a fake enum value
        class FakeModelType:
            value = "unknown"

        with pytest.raises(ValueError, match="Unknown model type"):
            create_model(FakeModelType())

    def test_factory_default_is_birdnet(self):
        """Test factory default argument creates BirdNetModel."""
        from model_service.birdnet_v2_model import BirdNetModel
        from model_service.model_factory import create_model

        model = create_model()
        assert isinstance(model, BirdNetModel)
