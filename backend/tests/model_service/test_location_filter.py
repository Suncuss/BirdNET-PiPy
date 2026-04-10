"""Tests for LocationFilter abstraction and implementations."""

import datetime
import logging
from unittest.mock import MagicMock

import numpy as np
import pytest

from model_service.base_model import ChunkPrediction

# ---------------------------------------------------------------------------
# _date_to_geomodel_week
# ---------------------------------------------------------------------------

class TestDateToGeomodelWeek:
    """Test the week conversion helper."""

    def test_jan_1(self):
        from model_service.location_filter import _date_to_geomodel_week

        dt = datetime.datetime(2025, 1, 1)
        assert _date_to_geomodel_week(dt) == 1

    def test_jan_7(self):
        from model_service.location_filter import _date_to_geomodel_week

        dt = datetime.datetime(2025, 1, 7)
        assert _date_to_geomodel_week(dt) == 1

    def test_jan_8(self):
        from model_service.location_filter import _date_to_geomodel_week

        dt = datetime.datetime(2025, 1, 8)
        assert _date_to_geomodel_week(dt) == 2

    def test_jan_14(self):
        from model_service.location_filter import _date_to_geomodel_week

        dt = datetime.datetime(2025, 1, 14)
        assert _date_to_geomodel_week(dt) == 2

    def test_jan_15(self):
        from model_service.location_filter import _date_to_geomodel_week

        dt = datetime.datetime(2025, 1, 15)
        assert _date_to_geomodel_week(dt) == 3

    def test_jan_22(self):
        from model_service.location_filter import _date_to_geomodel_week

        dt = datetime.datetime(2025, 1, 22)
        assert _date_to_geomodel_week(dt) == 4

    def test_feb_1(self):
        from model_service.location_filter import _date_to_geomodel_week

        dt = datetime.datetime(2025, 2, 1)
        assert _date_to_geomodel_week(dt) == 5

    def test_dec_25(self):
        from model_service.location_filter import _date_to_geomodel_week

        dt = datetime.datetime(2025, 12, 25)
        assert _date_to_geomodel_week(dt) == 48

    def test_dec_31(self):
        from model_service.location_filter import _date_to_geomodel_week

        dt = datetime.datetime(2025, 12, 31)
        assert _date_to_geomodel_week(dt) == 48

    def test_jun_15(self):
        """Mid-year sanity check: June 15 → week 23."""
        from model_service.location_filter import _date_to_geomodel_week

        dt = datetime.datetime(2025, 6, 15)
        assert _date_to_geomodel_week(dt) == 23


# ---------------------------------------------------------------------------
# NoFilter
# ---------------------------------------------------------------------------

class TestNoFilter:
    """Test NoFilter passthrough."""

    def test_filter_returns_disabled_context(self):
        from model_service.location_filter import LocationContext, NoFilter

        f = NoFilter()
        f.load()
        result = f.filter(42.0, -76.0, datetime.datetime(2025, 6, 15))
        assert isinstance(result, LocationContext)
        assert result.source == "disabled"
        assert result.allowed_species is None
        assert result.probabilities is None


# ---------------------------------------------------------------------------
# ModelBackedFilter
# ---------------------------------------------------------------------------

class TestModelBackedFilter:
    """Test ModelBackedFilter delegation to model.get_location_probabilities()."""

    def test_delegates_to_model(self):
        from model_service.location_filter import ModelBackedFilter

        model = MagicMock()
        model.get_location_probabilities.return_value = {
            "Species A_Common A": 0.2,
            "Species B_Common B": 0.01,
        }

        f = ModelBackedFilter(model)
        f.load()
        dt = datetime.datetime(2025, 6, 15)  # ISO week 24
        result = f.filter(42.0, -76.0, dt, threshold=0.03)

        model.get_location_probabilities.assert_called_once_with(42.0, -76.0, 24)
        assert result.source == "meta_model_v2.4"
        assert result.allowed_species == frozenset(["Species A_Common A"])
        assert result.probability_for("Species A_Common A") == 0.2
        assert result.probability_for("Species B_Common B") == 0.01

    def test_converts_datetime_to_iso_week(self):
        from model_service.location_filter import ModelBackedFilter

        model = MagicMock()
        model.get_location_probabilities.return_value = {}

        f = ModelBackedFilter(model)
        # January 1, 2025 → ISO week 1
        f.filter(0.0, 0.0, datetime.datetime(2025, 1, 1))
        _, _, week_arg = model.get_location_probabilities.call_args[0]
        assert week_arg == 1


# ---------------------------------------------------------------------------
# GeoModelFilter
# ---------------------------------------------------------------------------

class TestGeoModelFilter:
    """Test GeoModelFilter with mocked ONNX session."""

    BIRDNET_LABELS = [
        "Turdus migratorius_American Robin",
        "Cardinalis cardinalis_Northern Cardinal",
        "Cyanocitta cristata_Blue Jay",
        "Corvus brachyrhynchos_American Crow",
    ]

    # Geomodel labels: 3 species, only 2 overlap with BirdNET (Robin, Cardinal)
    GEOMODEL_LABELS_CONTENT = (
        "amerob\tTurdus migratorius\tAmerican Robin\n"
        "norcar\tCardinalis cardinalis\tNorthern Cardinal\n"
        "comchi\tPasser domesticus\tHouse Sparrow\n"  # not in BirdNET labels
    )

    @pytest.fixture
    def geomodel_labels_file(self, tmp_path):
        labels_file = tmp_path / "labels.txt"
        labels_file.write_text(self.GEOMODEL_LABELS_CONTENT)
        return str(labels_file)

    @pytest.fixture
    def mock_geo_filter(self, geomodel_labels_file):
        """Create a GeoModelFilter with mocked ONNX session."""
        from model_service.location_filter import GeoModelFilter

        f = GeoModelFilter(
            model_path="/fake/geomodel.onnx",
            labels_path=geomodel_labels_file,
            birdnet_labels=self.BIRDNET_LABELS,
        )

        # Mock the ONNX session (skip actual load)
        f._session = MagicMock()
        f._input_name = "input"
        f._output_name = "output"

        # Build label mapping from the real labels file
        from model_service.label_utils import parse_geomodel_labels
        geomodel_labels = parse_geomodel_labels(geomodel_labels_file)
        f._build_label_mapping(geomodel_labels)

        return f

    def test_label_mapping_maps_overlapping_species(self, mock_geo_filter):
        """Species present in both geomodel and BirdNET are mapped."""
        # Index 0 (Robin) and 1 (Cardinal) should be mapped
        assert 0 in mock_geo_filter._index_to_birdnet_label
        assert mock_geo_filter._index_to_birdnet_label[0] == "Turdus migratorius_American Robin"
        assert 1 in mock_geo_filter._index_to_birdnet_label
        assert mock_geo_filter._index_to_birdnet_label[1] == "Cardinalis cardinalis_Northern Cardinal"

    def test_label_mapping_excludes_non_birdnet_species(self, mock_geo_filter):
        """Geomodel species not in BirdNET are not mapped."""
        # Index 2 (House Sparrow) is not in BirdNET labels
        assert 2 not in mock_geo_filter._index_to_birdnet_label

    def test_unmapped_birdnet_species_identified(self, mock_geo_filter):
        """BirdNET species not in geomodel are tracked as unmapped."""
        unmapped = mock_geo_filter._unmapped_labels
        # Blue Jay and American Crow are in BirdNET but not in geomodel
        assert "Cyanocitta cristata_Blue Jay" in unmapped
        assert "Corvus brachyrhynchos_American Crow" in unmapped
        # Robin and Cardinal ARE mapped
        assert "Turdus migratorius_American Robin" not in unmapped
        assert "Cardinalis cardinalis_Northern Cardinal" not in unmapped

    def test_filter_returns_species_above_threshold_plus_unmapped(self, mock_geo_filter):
        """Filter returns mapped species above threshold + all unmapped species."""
        # Mock ONNX output: Robin=0.8, Cardinal=0.01, HouseSparrow=0.9
        probs = np.array([[0.8, 0.01, 0.9]])
        mock_geo_filter._session.run.return_value = [probs]

        dt = datetime.datetime(2025, 6, 15)
        result = mock_geo_filter.filter(42.0, -76.0, dt, threshold=0.03)

        assert result.source == "geomodel_v3"
        # Robin above threshold → included
        assert "Turdus migratorius_American Robin" in result.allowed_species
        # Cardinal below threshold → excluded
        assert "Cardinalis cardinalis_Northern Cardinal" not in result.allowed_species
        # Unmapped BirdNET species → always included
        assert "Cyanocitta cristata_Blue Jay" in result.allowed_species
        assert "Corvus brachyrhynchos_American Crow" in result.allowed_species
        assert result.probability_for("Turdus migratorius_American Robin") == 0.8
        assert result.probability_for("Cyanocitta cristata_Blue Jay") is None

    def test_filter_with_high_threshold_excludes_more(self, mock_geo_filter):
        """Higher threshold filters more aggressively."""
        probs = np.array([[0.5, 0.3, 0.9]])
        mock_geo_filter._session.run.return_value = [probs]

        dt = datetime.datetime(2025, 6, 15)
        result = mock_geo_filter.filter(42.0, -76.0, dt, threshold=0.6)

        # Robin 0.5 < 0.6 → excluded; Cardinal 0.3 < 0.6 → excluded
        assert "Turdus migratorius_American Robin" not in result.allowed_species
        assert "Cardinalis cardinalis_Northern Cardinal" not in result.allowed_species
        # Unmapped still included
        assert "Cyanocitta cristata_Blue Jay" in result.allowed_species

    def test_filter_caches_results(self, mock_geo_filter):
        """Same (lat, lon, week) reuses cached geomodel probabilities."""
        probs = np.array([[0.8, 0.5, 0.1]])
        mock_geo_filter._session.run.return_value = [probs]

        dt = datetime.datetime(2025, 6, 15)
        result1 = mock_geo_filter.filter(42.0, -76.0, dt, threshold=0.03)
        result2 = mock_geo_filter.filter(42.0, -76.0, dt, threshold=0.03)

        assert result1.allowed_species == result2.allowed_species
        # ONNX session.run called only once
        assert mock_geo_filter._session.run.call_count == 1

    def test_filter_different_threshold_reuses_cached_probabilities(self, mock_geo_filter):
        """Different thresholds reuse cached geomodel probabilities."""
        probs = np.array([[0.8, 0.5, 0.1]])
        mock_geo_filter._session.run.return_value = [probs]

        dt = datetime.datetime(2025, 6, 15)
        result1 = mock_geo_filter.filter(42.0, -76.0, dt, threshold=0.03)
        result2 = mock_geo_filter.filter(42.0, -76.0, dt, threshold=0.6)

        assert "Turdus migratorius_American Robin" in result1.allowed_species
        assert "Cardinalis cardinalis_Northern Cardinal" in result1.allowed_species
        assert "Turdus migratorius_American Robin" in result2.allowed_species
        assert "Cardinalis cardinalis_Northern Cardinal" not in result2.allowed_species
        assert mock_geo_filter._session.run.call_count == 1

    def test_filter_uses_geomodel_week(self, mock_geo_filter):
        """Filter converts datetime to geomodel week, not ISO week."""
        probs = np.array([[0.8, 0.5, 0.1]])
        mock_geo_filter._session.run.return_value = [probs]

        # June 15 → geomodel week 23 (month 6, day 15 → (5)*4 + 3 = 23)
        dt = datetime.datetime(2025, 6, 15)
        mock_geo_filter.filter(42.0, -76.0, dt)

        # session.run([output_name], {input_name: model_input})
        # positional args: args[0]=[output_name], args[1]={input_name: input}
        call_args = mock_geo_filter._session.run.call_args[0]
        input_dict = call_args[1]  # the feed dict
        call_input = input_dict[mock_geo_filter._input_name]
        assert call_input[0][2] == 23.0  # week column

    def test_filter_raises_if_not_loaded(self):
        """Filter raises RuntimeError if session not loaded."""
        from model_service.location_filter import GeoModelFilter

        f = GeoModelFilter("/fake.onnx", "/fake.txt", [])
        with pytest.raises(RuntimeError, match="not loaded"):
            f.filter(42.0, -76.0, datetime.datetime.now())


# ---------------------------------------------------------------------------
# Integration: process_audio_file with LocationFilter
# ---------------------------------------------------------------------------

class TestProcessAudioFileWithLocationFilter:
    """Integration tests for process_audio_file using LocationFilter."""

    @pytest.fixture
    def mock_model(self):

        model = MagicMock()
        model.name = "birdnet"
        model.version = "3.0"
        model.sample_rate = 32000
        model.chunk_length_seconds = 3.0
        model.get_ebird_code.return_value = None
        model.predict_chunk.return_value = ChunkPrediction(raw_top3=(), candidates=())
        return model

    @pytest.fixture
    def mock_location_filter(self):
        from model_service.location_filter import LocationContext, LocationFilter

        f = MagicMock(spec=LocationFilter)
        f.filter.return_value = LocationContext.disabled(0.03)
        return f

    def test_mapped_species_above_threshold_allowed(self, monkeypatch, mock_model, mock_location_filter):
        """Species in the location filter's output pass through."""
        from model_service import inference_server
        from model_service.location_filter import LocationContext

        # Model detects Robin

        mock_model.predict_chunk.return_value = ChunkPrediction(
            raw_top3=(("Turdus migratorius_American Robin", 0.9),),
            candidates=(("Turdus migratorius_American Robin", 0.9),),
        )

        mock_location_filter.filter.return_value = LocationContext(
            source="geomodel_v3",
            threshold=0.03,
            allowed_species=frozenset(["Turdus migratorius_American Robin"]),
            probabilities={"Turdus migratorius_American Robin": 0.8},
        )

        monkeypatch.setattr(
            inference_server, "split_audio",
            lambda *a, **kw: [np.zeros(96000, dtype=np.float32)]
        )

        results = inference_server.process_audio_file(
            model=mock_model,
            location_filter=mock_location_filter,
            audio_file_path="/tmp/20250615_103000.wav",
            lat=42.0, lon=-76.0,
            sensitivity=0.75, cutoff=0.60,
            overlap=0.0, recording_length=9.0,
            allowed_species=[], blocked_species=[],
        )

        assert len(results) == 1
        assert results[0]["common_name"] == "American Robin"

    def test_species_not_in_filter_rejected(self, monkeypatch, mock_model, mock_location_filter):
        """Species NOT in the location filter's output are rejected."""
        from model_service import inference_server
        from model_service.location_filter import LocationContext


        mock_model.predict_chunk.return_value = ChunkPrediction(
            raw_top3=(("Turdus migratorius_American Robin", 0.9),),
            candidates=(("Turdus migratorius_American Robin", 0.9),),
        )

        # Location filter does NOT include Robin
        mock_location_filter.filter.return_value = LocationContext(
            source="geomodel_v3",
            threshold=0.03,
            allowed_species=frozenset(["Cardinalis cardinalis_Northern Cardinal"]),
            probabilities={"Cardinalis cardinalis_Northern Cardinal": 0.7},
        )

        monkeypatch.setattr(
            inference_server, "split_audio",
            lambda *a, **kw: [np.zeros(96000, dtype=np.float32)]
        )

        results = inference_server.process_audio_file(
            model=mock_model,
            location_filter=mock_location_filter,
            audio_file_path="/tmp/20250615_103000.wav",
            lat=42.0, lon=-76.0,
            sensitivity=0.75, cutoff=0.60,
            overlap=0.0, recording_length=9.0,
            allowed_species=[], blocked_species=[],
        )

        assert len(results) == 0

    def test_unmapped_species_pass_through(self, monkeypatch, mock_model, mock_location_filter):
        """Unmapped species (included in filter output) pass through."""
        from model_service import inference_server
        from model_service.location_filter import LocationContext

        # Model detects Blue Jay (which is unmapped in geomodel)

        mock_model.predict_chunk.return_value = ChunkPrediction(
            raw_top3=(("Cyanocitta cristata_Blue Jay", 0.85),),
            candidates=(("Cyanocitta cristata_Blue Jay", 0.85),),
        )

        # Location filter output includes Blue Jay as unmapped
        mock_location_filter.filter.return_value = LocationContext(
            source="geomodel_v3",
            threshold=0.03,
            allowed_species=frozenset([
                "Turdus migratorius_American Robin",
                "Cyanocitta cristata_Blue Jay",
            ]),
            probabilities={"Turdus migratorius_American Robin": 0.8},
        )

        monkeypatch.setattr(
            inference_server, "split_audio",
            lambda *a, **kw: [np.zeros(96000, dtype=np.float32)]
        )

        results = inference_server.process_audio_file(
            model=mock_model,
            location_filter=mock_location_filter,
            audio_file_path="/tmp/20250615_103000.wav",
            lat=42.0, lon=-76.0,
            sensitivity=0.75, cutoff=0.60,
            overlap=0.0, recording_length=9.0,
            allowed_species=[], blocked_species=[],
        )

        assert len(results) == 1
        assert results[0]["common_name"] == "Blue Jay"

    def test_no_filter_allows_all(self, monkeypatch, mock_model, mock_location_filter):
        """When filtering is disabled, all detections pass through."""
        from model_service import inference_server
        from model_service.location_filter import LocationContext


        mock_model.predict_chunk.return_value = ChunkPrediction(
            raw_top3=(("Turdus migratorius_American Robin", 0.9),),
            candidates=(("Turdus migratorius_American Robin", 0.9),),
        )
        mock_location_filter.filter.return_value = LocationContext.disabled(0.03)

        monkeypatch.setattr(
            inference_server, "split_audio",
            lambda *a, **kw: [np.zeros(96000, dtype=np.float32)]
        )

        results = inference_server.process_audio_file(
            model=mock_model,
            location_filter=mock_location_filter,
            audio_file_path="/tmp/20250615_103000.wav",
            lat=42.0, lon=-76.0,
            sensitivity=0.75, cutoff=0.60,
            overlap=0.0, recording_length=9.0,
            allowed_species=[], blocked_species=[],
        )

        assert len(results) == 1

    def test_uses_file_timestamp_not_now(self, monkeypatch, mock_model, mock_location_filter):
        """Filter is called with the recording timestamp parsed from filename."""
        from model_service import inference_server
        from model_service.location_filter import LocationContext


        mock_model.predict_chunk.return_value = ChunkPrediction(raw_top3=(), candidates=())
        mock_location_filter.filter.return_value = LocationContext.disabled(0.03)

        monkeypatch.setattr(
            inference_server, "split_audio",
            lambda *a, **kw: [np.zeros(96000, dtype=np.float32)]
        )

        inference_server.process_audio_file(
            model=mock_model,
            location_filter=mock_location_filter,
            audio_file_path="/tmp/20250115_083000.wav",
            lat=42.0, lon=-76.0,
            sensitivity=0.75, cutoff=0.60,
            overlap=0.0, recording_length=9.0,
            allowed_species=[], blocked_species=[],
        )

        # Filter should be called with the file timestamp (Jan 15, 2025 08:30)
        call_args = mock_location_filter.filter.call_args
        dt_arg = call_args[0][2]
        assert dt_arg == datetime.datetime(2025, 1, 15, 8, 30, 0)

    def test_blocked_species_override_location_filter(self, monkeypatch, mock_model, mock_location_filter):
        """Blocked species are rejected even if location filter allows them."""
        from model_service import inference_server
        from model_service.location_filter import LocationContext


        mock_model.predict_chunk.return_value = ChunkPrediction(
            raw_top3=(("Turdus migratorius_American Robin", 0.9),),
            candidates=(("Turdus migratorius_American Robin", 0.9),),
        )
        mock_location_filter.filter.return_value = LocationContext(
            source="geomodel_v3",
            threshold=0.03,
            allowed_species=frozenset(["Turdus migratorius_American Robin"]),
            probabilities={"Turdus migratorius_American Robin": 0.8},
        )

        monkeypatch.setattr(
            inference_server, "split_audio",
            lambda *a, **kw: [np.zeros(96000, dtype=np.float32)]
        )

        results = inference_server.process_audio_file(
            model=mock_model,
            location_filter=mock_location_filter,
            audio_file_path="/tmp/20250615_103000.wav",
            lat=42.0, lon=-76.0,
            sensitivity=0.75, cutoff=0.60,
            overlap=0.0, recording_length=9.0,
            allowed_species=[],
            blocked_species=["Turdus migratorius"],
        )

        assert len(results) == 0

    def test_detection_log_includes_location_probability(self, monkeypatch, mock_model, mock_location_filter, caplog):
        """Confirmed detections log mapped location probability and source."""
        from model_service import inference_server
        from model_service.location_filter import LocationContext


        mock_model.predict_chunk.return_value = ChunkPrediction(
            raw_top3=(("Turdus migratorius_American Robin", 0.9),),
            candidates=(("Turdus migratorius_American Robin", 0.9),),
        )
        mock_location_filter.filter.return_value = LocationContext(
            source="geomodel_v3",
            threshold=0.03,
            allowed_species=frozenset(["Turdus migratorius_American Robin"]),
            probabilities={"Turdus migratorius_American Robin": 0.8},
        )

        monkeypatch.setattr(
            inference_server, "split_audio",
            lambda *a, **kw: [np.zeros(96000, dtype=np.float32)]
        )

        with caplog.at_level(logging.INFO):
            inference_server.process_audio_file(
                model=mock_model,
                location_filter=mock_location_filter,
                audio_file_path="/tmp/20250615_103000.wav",
                lat=42.0, lon=-76.0,
                sensitivity=0.75, cutoff=0.60,
                overlap=0.0, recording_length=9.0,
                allowed_species=[], blocked_species=[],
            )

        detection_logs = [record for record in caplog.records if record.message == "Bird detected"]
        assert len(detection_logs) == 1
        assert detection_logs[0].location_source == "geomodel_v3"
        assert detection_logs[0].location_prob == 80.0

    def test_chunk_log_includes_location_probability(self, monkeypatch, mock_model, mock_location_filter, caplog):
        """Chunk-level top-3 log includes active location probabilities."""
        from model_service import inference_server
        from model_service.location_filter import LocationContext

        mock_model.predict_chunk.return_value = ChunkPrediction(
            raw_top3=(
                ("Turdus migratorius_American Robin", 0.9),
                ("Cardinalis cardinalis_Northern Cardinal", 0.7),
            ),
            candidates=(("Turdus migratorius_American Robin", 0.9),),
        )
        mock_location_filter.filter.return_value = LocationContext(
            source="geomodel_v3",
            threshold=0.03,
            allowed_species=frozenset(["Turdus migratorius_American Robin"]),
            probabilities={"Turdus migratorius_American Robin": 0.8},
        )

        monkeypatch.setattr(
            inference_server, "split_audio",
            lambda *a, **kw: [np.zeros(96000, dtype=np.float32)]
        )

        with caplog.at_level(logging.INFO):
            inference_server.process_audio_file(
                model=mock_model,
                location_filter=mock_location_filter,
                audio_file_path="/tmp/20250615_103000.wav",
                lat=42.0, lon=-76.0,
                sensitivity=0.75, cutoff=0.60,
                overlap=0.0, recording_length=9.0,
                allowed_species=[], blocked_species=[],
            )

        chunk_logs = [record for record in caplog.records if record.message == "Chunk 0 raw model output"]
        assert len(chunk_logs) == 1
        assert chunk_logs[0].location_source == "geomodel_v3"
        assert chunk_logs[0].top3 == [
            {'species': 'American Robin', 'confidence': 90.0, 'location_prob': 80.0},
            {'species': 'Northern Cardinal', 'confidence': 70.0, 'location_prob': 'unmapped'},
        ]

    def test_detection_log_marks_unmapped_species(self, monkeypatch, mock_model, mock_location_filter, caplog):
        """Confirmed detections log unmapped when the species has no geomodel entry."""
        from model_service import inference_server
        from model_service.location_filter import LocationContext

        mock_model.predict_chunk.return_value = ChunkPrediction(
            raw_top3=(("Cyanocitta cristata_Blue Jay", 0.85),),
            candidates=(("Cyanocitta cristata_Blue Jay", 0.85),),
        )
        mock_location_filter.filter.return_value = LocationContext(
            source="geomodel_v3",
            threshold=0.03,
            allowed_species=frozenset(["Cyanocitta cristata_Blue Jay"]),
            probabilities={"Turdus migratorius_American Robin": 0.8},
        )

        monkeypatch.setattr(
            inference_server, "split_audio",
            lambda *a, **kw: [np.zeros(96000, dtype=np.float32)]
        )

        with caplog.at_level(logging.INFO):
            inference_server.process_audio_file(
                model=mock_model,
                location_filter=mock_location_filter,
                audio_file_path="/tmp/20250615_103000.wav",
                lat=42.0, lon=-76.0,
                sensitivity=0.75, cutoff=0.60,
                overlap=0.0, recording_length=9.0,
                allowed_species=[], blocked_species=[],
            )

        detection_logs = [record for record in caplog.records if record.message == "Bird detected"]
        assert len(detection_logs) == 1
        assert detection_logs[0].location_source == "geomodel_v3"
        assert detection_logs[0].location_prob == "unmapped"
