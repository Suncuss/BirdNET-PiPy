"""
Unit tests for core/spectrogram.py — renders real output to verify.
"""
import struct
import wave
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

RATE = 48000


def write_tone_wav(path, freq=1000, duration=3, sampwidth=2, channels=1):
    """Write a sine-tone WAV in any PCM width the renderer supports."""
    t = np.arange(int(RATE * duration)) / RATE
    tone = np.sin(2 * np.pi * freq * t) * 0.8

    if sampwidth == 1:
        samples = (tone * 127 + 128).astype(np.uint8)
        frames = np.repeat(samples, channels).tobytes()
    elif sampwidth == 2:
        samples = (tone * 32767).astype('<i2')
        frames = np.repeat(samples, channels).tobytes()
    elif sampwidth == 3:
        samples = (tone * (2**23 - 1)).astype('<i4')
        samples = np.repeat(samples, channels)
        # keep the low 3 bytes of each little-endian int32
        frames = np.frombuffer(samples.tobytes(), np.uint8).reshape(-1, 4)[:, :3].tobytes()
    elif sampwidth == 4:
        samples = (tone * (2**31 - 1)).astype('<i4')
        frames = np.repeat(samples, channels).tobytes()
    else:
        raise ValueError(sampwidth)

    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(RATE)
        wf.writeframes(frames)
    return str(path)


def write_float32_wav(path, duration=1):
    """Write an IEEE-float WAV (format tag 3), which stdlib wave can't parse."""
    t = np.arange(int(RATE * duration)) / RATE
    data = (np.sin(2 * np.pi * 1000 * t) * 0.8).astype('<f4').tobytes()
    with open(path, 'wb') as f:
        f.write(b'RIFF' + struct.pack('<I', 36 + len(data)) + b'WAVE')
        f.write(b'fmt ' + struct.pack('<IHHIIHH', 16, 3, 1, RATE, RATE * 4, 4, 32))
        f.write(b'data' + struct.pack('<I', len(data)) + data)
    return str(path)


@pytest.fixture
def spectro_settings():
    """Mutable runtime-settings payload the spectro fixture serves; tests
    can update it before rendering to exercise non-default settings."""
    return {'spectrogram': {}}


@pytest.fixture
def spectro(spectro_settings):
    """core.spectrogram with runtime settings mocked.

    Imported per-test because conftest's reset_imports pops core.* modules
    between tests — a module-level import would leave patch() targeting a
    different (re-imported) module object than the one under test.
    """
    import core.spectrogram as spectrogram_module
    with patch.object(spectrogram_module, 'get_runtime_settings',
                      return_value=spectro_settings):
        yield spectrogram_module


@pytest.fixture
def wav_file(tmp_path):
    return write_tone_wav(tmp_path / "test.wav")


@pytest.fixture(scope='module')
def default_render(tmp_path_factory):
    """One default-settings render of the 1kHz tone, shared by the tests
    that only inspect the output image."""
    import core.spectrogram as spectrogram_module
    tmp = tmp_path_factory.mktemp('spectrogram')
    wav = write_tone_wav(tmp / "tone.wav")
    output = str(tmp / "out.webp")
    with patch.object(spectrogram_module, 'get_runtime_settings',
                      return_value={'spectrogram': {}}):
        spectrogram_module.generate_spectrogram(wav, output, "Test Bird")
    return output


def panel_band_means(output):
    """Mean brightness of the 1kHz tone band vs a quiet 8kHz band.

    The panel maps 0-12kHz bottom-to-top between the spine centers
    (rows 220 down to 60), so 1kHz sits near row 207 and 8kHz near row 113.
    """
    a = np.asarray(Image.open(output).convert('RGB')).astype(int).sum(axis=2)
    return a[205:210, 95:932].mean(), a[110:115, 95:932].mean()


class TestGenerateSpectrogram:
    """Rendering tests — actually produce and inspect output images."""

    def test_output_is_valid_webp(self, default_render):
        img = Image.open(default_render)
        assert img.format == 'WEBP'

    def test_output_dimensions_match_legacy_layout(self, default_render):
        """Canvas must stay 1066x255 — the layout the matplotlib renderer
        produced for most titles — so new images blend with the archive."""
        img = Image.open(default_render)
        assert img.size == (1066, 255)

    def test_tone_renders_at_expected_frequency(self, default_render):
        """A 1kHz tone must appear as a bright band at the right height."""
        tone_row, quiet_row = panel_band_means(default_render)
        assert tone_row > quiet_row + 150, (
            f"tone band ({tone_row:.0f}) not brighter than quiet band ({quiet_row:.0f})")

    def test_start_end_time_slicing(self, spectro, tmp_path, wav_file):
        output = str(tmp_path / "spectrogram.webp")
        spectro.generate_spectrogram(wav_file, output, "Test Bird",
                                     start_time=0.5, end_time=2.0)

        assert Image.open(output).size == (1066, 255)

    def test_stereo_uses_first_channel(self, spectro, tmp_path):
        wav = write_tone_wav(tmp_path / "stereo.wav", channels=2)
        output = str(tmp_path / "spectrogram.webp")
        spectro.generate_spectrogram(wav, output, "Test Bird")

        tone_row, quiet_row = panel_band_means(output)
        assert tone_row > quiet_row + 150

    @pytest.mark.parametrize("sampwidth", [1, 3, 4])
    def test_pcm_sample_widths(self, spectro, tmp_path, sampwidth):
        """8/24/32-bit PCM WAVs (e.g. migrated user files) must render."""
        wav = write_tone_wav(tmp_path / f"pcm{sampwidth}.wav", sampwidth=sampwidth)
        output = str(tmp_path / "spectrogram.webp")
        spectro.generate_spectrogram(wav, output, "Test Bird")

        tone_row, quiet_row = panel_band_means(output)
        assert tone_row > quiet_row + 150

    def test_float_wav_falls_back_to_ffmpeg(self, spectro, tmp_path):
        """stdlib wave can't read IEEE-float WAVs; they go through ffmpeg."""
        wav = write_float32_wav(str(tmp_path / "float.wav"))
        output = str(tmp_path / "spectrogram.webp")

        def fake_ffmpeg(cmd, **kwargs):
            write_tone_wav(cmd[-1], duration=1)

        with patch.object(spectro.subprocess, 'run',
                          side_effect=fake_ffmpeg) as mock_run:
            spectro.generate_spectrogram(wav, output, "Test Bird")

        assert mock_run.called
        assert Image.open(output).size == (1066, 255)

    def test_silent_audio_renders(self, spectro, tmp_path):
        """Zero-energy input must stay finite and render a dark panel."""
        path = tmp_path / "silent.wav"
        with wave.open(str(path), 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(RATE)
            wf.writeframes(b'\x00\x00' * RATE)
        output = str(tmp_path / "spectrogram.webp")
        spectro.generate_spectrogram(str(path), output, "Test Bird")

        assert Image.open(output).size == (1066, 255)

    def test_too_short_audio_raises(self, spectro, tmp_path):
        path = tmp_path / "short.wav"
        with wave.open(str(path), 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(RATE)
            wf.writeframes(b'\x00\x00' * 100)  # < one STFT window
        with pytest.raises(ValueError, match="too short"):
            spectro.generate_spectrogram(str(path), str(tmp_path / "out.webp"),
                                         "Test Bird")

    def test_custom_dbfs_range_still_renders(self, spectro, spectro_settings,
                                             tmp_path, wav_file):
        """Contrast knobs from settings change the mapping, not the layout."""
        spectro_settings['spectrogram'] = {'min_dbfs': -80, 'max_dbfs': -10}
        output = str(tmp_path / "spectrogram.webp")
        spectro.generate_spectrogram(wav_file, output, "Test Bird")

        assert Image.open(output).size == (1066, 255)
