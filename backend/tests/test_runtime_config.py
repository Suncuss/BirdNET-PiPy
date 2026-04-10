"""Tests for runtime setting change classification."""

from core.runtime_config import _sources_only_labels_changed, classify_setting_changes


def _make_settings(sources):
    """Helper to wrap sources list in settings structure."""
    return {"audio": {"sources": sources}}


class TestClassifySettingChanges:
    def test_model_switch_requires_full_restart(self):
        plan = classify_setting_changes(["model.type"])

        assert plan["full_restart_required"] is True
        assert "model.type" in plan["full_restart_paths"]

    def test_audio_overlap_is_component_restart_only(self):
        plan = classify_setting_changes(["audio.overlap"])

        assert plan["full_restart_required"] is False
        assert "audio.overlap" in plan["component_restarts"]

    def test_audio_sources_change_requires_full_restart(self):
        plan = classify_setting_changes(["audio.sources.0.enabled"])

        assert plan["full_restart_required"] is True
        assert "audio.sources.0.enabled" in plan["full_restart_paths"]

    def test_audio_next_source_id_requires_full_restart(self):
        plan = classify_setting_changes(["audio.next_source_id"])

        assert plan["full_restart_required"] is True
        assert "audio.next_source_id" in plan["full_restart_paths"]

    def test_audio_recording_length_is_component_restart(self):
        plan = classify_setting_changes(["audio.recording_length"])

        assert plan["full_restart_required"] is False
        assert "audio.recording_length" in plan["component_restarts"]

    def test_location_change_is_hot_applied(self):
        """Location is read live from config — no restart needed."""
        plan = classify_setting_changes(["location.latitude", "location.longitude", "location.timezone"])

        assert plan["full_restart_required"] is False
        assert "location.latitude" in plan["hot_applied"]
        assert "location.longitude" in plan["hot_applied"]
        assert "location.timezone" in plan["hot_applied"]


class TestSourceLabelOnlyChanges:
    """Tests for label-only source edits skipping restart."""

    def test_label_only_change_is_hot_applied(self):
        old = _make_settings([
            {"id": "source_0", "type": "pulseaudio", "device": "default", "label": "Old Name"}
        ])
        new = _make_settings([
            {"id": "source_0", "type": "pulseaudio", "device": "default", "label": "New Name"}
        ])

        plan = classify_setting_changes(["audio.sources"], old, new)

        assert plan["full_restart_required"] is False
        assert "audio.sources" in plan["hot_applied"]

    def test_label_change_with_url_change_requires_restart(self):
        old = _make_settings([
            {"id": "source_0", "type": "rtsp", "url": "rtsp://old", "label": "Old"}
        ])
        new = _make_settings([
            {"id": "source_0", "type": "rtsp", "url": "rtsp://new", "label": "New"}
        ])

        plan = classify_setting_changes(["audio.sources"], old, new)

        assert plan["full_restart_required"] is True
        assert "audio.sources" in plan["full_restart_paths"]

    def test_label_change_with_device_change_requires_restart(self):
        old = _make_settings([
            {"id": "source_0", "type": "pulseaudio", "device": "default", "label": "Mic"}
        ])
        new = _make_settings([
            {"id": "source_0", "type": "pulseaudio", "device": "hw:1,0", "label": "Mic"}
        ])

        plan = classify_setting_changes(["audio.sources"], old, new)

        assert plan["full_restart_required"] is True

    def test_source_added_requires_restart(self):
        old = _make_settings([
            {"id": "source_0", "type": "pulseaudio", "device": "default", "label": "Mic"}
        ])
        new = _make_settings([
            {"id": "source_0", "type": "pulseaudio", "device": "default", "label": "Mic"},
            {"id": "source_1", "type": "rtsp", "url": "rtsp://cam", "label": "Cam"}
        ])

        plan = classify_setting_changes(["audio.sources"], old, new)

        assert plan["full_restart_required"] is True

    def test_source_removed_requires_restart(self):
        old = _make_settings([
            {"id": "source_0", "type": "pulseaudio", "device": "default", "label": "Mic"},
            {"id": "source_1", "type": "rtsp", "url": "rtsp://cam", "label": "Cam"}
        ])
        new = _make_settings([
            {"id": "source_0", "type": "pulseaudio", "device": "default", "label": "Mic"}
        ])

        plan = classify_setting_changes(["audio.sources"], old, new)

        assert plan["full_restart_required"] is True

    def test_enabled_toggle_requires_restart(self):
        old = _make_settings([
            {"id": "source_0", "type": "rtsp", "url": "rtsp://a", "label": "A", "enabled": True}
        ])
        new = _make_settings([
            {"id": "source_0", "type": "rtsp", "url": "rtsp://a", "label": "A", "enabled": False}
        ])

        plan = classify_setting_changes(["audio.sources"], old, new)

        assert plan["full_restart_required"] is True

    def test_multiple_sources_label_only_is_hot_applied(self):
        old = _make_settings([
            {"id": "source_0", "type": "pulseaudio", "device": "default", "label": "Old Mic"},
            {"id": "source_1", "type": "rtsp", "url": "rtsp://cam", "label": "Old Cam"}
        ])
        new = _make_settings([
            {"id": "source_0", "type": "pulseaudio", "device": "default", "label": "New Mic"},
            {"id": "source_1", "type": "rtsp", "url": "rtsp://cam", "label": "New Cam"}
        ])

        plan = classify_setting_changes(["audio.sources"], old, new)

        assert plan["full_restart_required"] is False
        assert "audio.sources" in plan["hot_applied"]

    def test_one_label_change_one_url_change_requires_restart(self):
        old = _make_settings([
            {"id": "source_0", "type": "pulseaudio", "device": "default", "label": "Old Mic"},
            {"id": "source_1", "type": "rtsp", "url": "rtsp://old", "label": "Cam"}
        ])
        new = _make_settings([
            {"id": "source_0", "type": "pulseaudio", "device": "default", "label": "New Mic"},
            {"id": "source_1", "type": "rtsp", "url": "rtsp://new", "label": "Cam"}
        ])

        plan = classify_setting_changes(["audio.sources"], old, new)

        assert plan["full_restart_required"] is True

    def test_without_old_new_settings_falls_back_to_full_restart(self):
        """Backward compatibility: no old/new settings means full restart."""
        plan = classify_setting_changes(["audio.sources"])

        assert plan["full_restart_required"] is True
        assert "audio.sources" in plan["full_restart_paths"]

    def test_source_id_changed_requires_restart(self):
        old = _make_settings([
            {"id": "source_0", "type": "rtsp", "url": "rtsp://a", "label": "A"}
        ])
        new = _make_settings([
            {"id": "source_1", "type": "rtsp", "url": "rtsp://a", "label": "A"}
        ])

        plan = classify_setting_changes(["audio.sources"], old, new)

        assert plan["full_restart_required"] is True

    def test_label_only_mixed_with_other_restart_paths(self):
        """Label change + model change: model still triggers restart."""
        old = _make_settings([
            {"id": "source_0", "type": "pulseaudio", "device": "default", "label": "Old"}
        ])
        new = _make_settings([
            {"id": "source_0", "type": "pulseaudio", "device": "default", "label": "New"}
        ])

        plan = classify_setting_changes(
            ["audio.sources", "model.type"], old, new
        )

        assert plan["full_restart_required"] is True
        assert "model.type" in plan["full_restart_paths"]
        assert "audio.sources" in plan["hot_applied"]

    def test_next_source_id_still_requires_restart_with_label_only(self):
        """next_source_id change isn't affected by label-only exemption."""
        old = _make_settings([
            {"id": "source_0", "type": "pulseaudio", "device": "default", "label": "Old"}
        ])
        new = _make_settings([
            {"id": "source_0", "type": "pulseaudio", "device": "default", "label": "New"}
        ])

        plan = classify_setting_changes(
            ["audio.sources", "audio.next_source_id"], old, new
        )

        assert plan["full_restart_required"] is True
        assert "audio.next_source_id" in plan["full_restart_paths"]
        assert "audio.sources" in plan["hot_applied"]


class TestSourcesOnlyLabelsChanged:
    """Direct tests for the _sources_only_labels_changed helper."""

    def test_identical_sources(self):
        settings = _make_settings([
            {"id": "source_0", "type": "pulseaudio", "device": "default", "label": "Mic"}
        ])
        assert _sources_only_labels_changed(settings, settings) is True

    def test_label_differs(self):
        old = _make_settings([{"id": "s0", "type": "rtsp", "url": "rtsp://a", "label": "A"}])
        new = _make_settings([{"id": "s0", "type": "rtsp", "url": "rtsp://a", "label": "B"}])
        assert _sources_only_labels_changed(old, new) is True

    def test_url_differs(self):
        old = _make_settings([{"id": "s0", "type": "rtsp", "url": "rtsp://a", "label": "A"}])
        new = _make_settings([{"id": "s0", "type": "rtsp", "url": "rtsp://b", "label": "A"}])
        assert _sources_only_labels_changed(old, new) is False

    def test_different_count(self):
        old = _make_settings([{"id": "s0", "type": "rtsp", "url": "rtsp://a", "label": "A"}])
        new = _make_settings([])
        assert _sources_only_labels_changed(old, new) is False

    def test_different_ids(self):
        old = _make_settings([{"id": "s0", "type": "rtsp", "url": "rtsp://a", "label": "A"}])
        new = _make_settings([{"id": "s1", "type": "rtsp", "url": "rtsp://a", "label": "A"}])
        assert _sources_only_labels_changed(old, new) is False

    def test_empty_sources(self):
        old = _make_settings([])
        new = _make_settings([])
        assert _sources_only_labels_changed(old, new) is True

    def test_missing_audio_key(self):
        assert _sources_only_labels_changed({}, {}) is True

    def test_label_added_where_none_existed(self):
        old = _make_settings([{"id": "s0", "type": "pulseaudio", "device": "default"}])
        new = _make_settings([{"id": "s0", "type": "pulseaudio", "device": "default", "label": "Mic"}])
        assert _sources_only_labels_changed(old, new) is True

    def test_label_removed(self):
        old = _make_settings([{"id": "s0", "type": "pulseaudio", "device": "default", "label": "Mic"}])
        new = _make_settings([{"id": "s0", "type": "pulseaudio", "device": "default"}])
        assert _sources_only_labels_changed(old, new) is True
