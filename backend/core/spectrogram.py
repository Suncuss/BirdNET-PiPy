"""Detection spectrogram rendering with numpy + PIL.

Replaces the previous matplotlib/scipy pipeline: the STFT is computed with
plain numpy (verified numerically identical to scipy.signal.spectrogram with
the same window/overlap/scaling), colormapped through an embedded Greens_r
LUT, and composed with PIL. This keeps ~85MB of matplotlib+scipy out of the
recording process and renders ~4x faster per detection.

The layout constants below were measured pixel-by-pixel against the
matplotlib output (1066x255, its majority tight-bbox size) so new images are
indistinguishable from the existing archive.
"""
import base64
import logging
import math
import os
import subprocess
import tempfile
import threading
import wave
from functools import lru_cache

from config.settings import SPECTROGRAM_FONT_PATH
from core.runtime_config import get_runtime_settings

logger = logging.getLogger(__name__)

# 256-entry RGB LUT of matplotlib's Greens_r colormap (768 bytes).
# Regenerate with:
#   from matplotlib import colormaps; import numpy as np, base64
#   lut = (colormaps['Greens_r'](np.linspace(0,1,256))[:,:3]*255+0.5).astype(np.uint8)
#   base64.b64encode(lut.tobytes())
_GREENS_R_LUT_B64 = (
    'AEQbAEUcAEccAEgdAEkdAEoeAEweAE0fAE4fAFAgAFEgAFIhAFMhAFUiAFYiAFcjAFkkAFokAFsl'
    'AFwlAF4mAF8mAGAnAGInAGMoAGQoAGUpAGcpAGgqAGkqAGsrAGwsAG0sAW4tAm8uA3AuBXEvBnIw'
    'B3MxCHQyCXUyCnYzC3c0DHc1DXg2Dnk2EHo3EXs4Enw5E305FH46FX87FoA8F4E9GII9GYM+GoQ/'
    'HIVAHYZAHodBH4dCIIhDIYlEIopEI4tFJIxGJY1HJo5HJ49IKJBJKZFKKpJKK5NLLJRMLZVNLpZN'
    'L5dOL5hPMJlQMZpQMptRM5xSNJ1TNZ5TNp9UN6BVOKFWOaJXOqNXO6RYPKVZPaZaPqdaP6hbP6lc'
    'QKpdQqtdQ6xeRa1fRq5gSK5gSq9hS7BiTbFjTrJkULJkUrNlU7RmVbVnVrVnWLZoWrdpW7hqXblr'
    'XrlrYLpsYrttY7xuZb1vZr1vaL5war9xa8BybcBybsFzcMJ0csN1c8R2dcR3dsV4eMZ5ecZ6esd7'
    'fMh8fch+f8l/gMqAgcqBg8uChMyDhsyFh82GiM6His6Ii8+JjdCKjtCLkNGNkdKOktKPlNOQldOR'
    'l9SSmNWUmdWVm9aWnNeXnteYn9iZoNmbotmco9qdpNqepdufp9ugqNyiqdyjqt2kq92lrN6mrt6n'
    'r9+osN+qseCrsuCstOGtteGutuKvt+KxuOOyuuOzu+S0vOS1veW2vuW4wOa5wea6wue7w+e8xOi9'
    'xui/x+nAyOnByerCyurDy+rEy+vFzOvGzezHzuzIz+zJ0O3K0e3L0u3M0+7N1O7O1e/P1u/Q1+/R'
    '2PDS2fDT2vDU2/HV2/HW3PLX3fLY3vLZ3/Pa4PPb4fPc4vTd4/Te5PXf5fXg5fXh5vXh5/bi5/bj'
    '6Pbj6Pbk6ffl6ffl6vfm6/fn6/fn7Pjo7Pjo7fjp7fjq7vjq7/nr7/ns8Pns8Pnt8fru8fru8vrv'
    '8vrw8/rw9Pvx9Pvy9fvy9fvz9vz09vz09/z1'
)

# Canvas layout, measured from the matplotlib reference at 250 DPI.
_W, _H = 1066, 255
_PANEL = (92, 59, 934, 221)   # spectrogram box, outer spine edges (inclusive)
_CBAR = (942, 59, 953, 221)   # colorbar box
_SPINE = 3                    # mpl 0.8pt linewidth
_TICK_LEN = 11                # mpl ytick.major.size 3.5pt
_TICK_PAD = 14                # mpl ytick.major.pad 3.5pt
_TICK_TEXT_DY = 9             # tick label vertical centering at _TICK_SIZE
_TICK_BEARING = 2             # textlength includes side bearings; mpl pads from glyph ink
_TITLE_Y = 20
# mpl pt sizes at 250 DPI: title 7pt, axis labels 6pt, tick labels 5pt
_TITLE_SIZE = 24.5
_LABEL_SIZE = 21
_TICK_SIZE = 17.4
_MINUS = '−'             # mpl renders ticks with unicode minus

_STFT_NPERSEG = 256
_STFT_NOVERLAP = 128

_render_runtime = None
_render_runtime_lock = threading.Lock()


def _rotated_text_mask(text, font):
    """Rasterize text rotated 90° CCW as an alpha mask, so pasting it never
    paints over neighboring elements."""
    from PIL import Image, ImageDraw

    width = int(font.getlength(text))
    tile = Image.new('L', (width, 26), 0)
    ImageDraw.Draw(tile).text((0, 0), text, fill=255, font=font)
    return tile.rotate(90, expand=True)


def _get_render_runtime():
    """Lazy-load numpy/PIL and build the per-process render constants
    (fonts, colormap LUT, colorbar gradient, rotated axis-label masks)."""
    global _render_runtime
    if _render_runtime is not None:
        return _render_runtime

    with _render_runtime_lock:
        if _render_runtime is not None:
            return _render_runtime

        import numpy as np
        from PIL import Image, ImageFont

        sizes = {'title': _TITLE_SIZE, 'label': _LABEL_SIZE, 'tick': _TICK_SIZE}
        try:
            fonts = {name: ImageFont.truetype(SPECTROGRAM_FONT_PATH, size)
                     for name, size in sizes.items()}
        except OSError:
            logger.warning("Spectrogram font missing at %s, using PIL default",
                           SPECTROGRAM_FONT_PATH)
            fonts = {name: ImageFont.load_default(size)
                     for name, size in sizes.items()}

        lut = np.frombuffer(base64.b64decode(_GREENS_R_LUT_B64),
                            dtype=np.uint8).reshape(256, 3)

        cx0, cy0, cx1, cy1 = _CBAR
        grad = lut[np.linspace(255, 0, cy1 - cy0 + 1 - 2 * _SPINE)
                   .round().astype(np.uint8)][:, None, :]
        grad = np.repeat(grad, cx1 - cx0 + 1 - 2 * _SPINE, axis=1)

        _render_runtime = {
            'fonts': fonts,
            'lut': lut,
            'cbar_gradient': Image.fromarray(grad),
            'ylabel_mask': _rotated_text_mask('Frequency [kHz]', fonts['label']),
            'clabel_mask': _rotated_text_mask('Intensity [dBFS]', fonts['label']),
        }
        return _render_runtime


def _read_wav(path, start_time=0, end_time=None):
    """Read a WAV file as (rate, float64 mono samples in [-1, 1]), sliced to
    [start_time, end_time) before the float conversion so only the needed
    window is converted.

    Handles 8/16/24/32-bit PCM with stdlib wave. Non-PCM WAVs (e.g. float32,
    possible via migration of user-supplied files) are converted through
    ffmpeg first — stdlib wave cannot parse them.
    """
    import numpy as np

    try:
        with wave.open(path, 'rb') as wf:
            rate = wf.getframerate()
            nch = wf.getnchannels()
            width = wf.getsampwidth()
            frames = wf.readframes(wf.getnframes())
    except wave.Error:
        return _read_wav_via_ffmpeg(path, start_time, end_time)

    start = int(start_time * rate)
    end = int(end_time * rate) if end_time else None

    if width == 3:
        # 24-bit little-endian PCM: assemble bytes, sign-extend, normalize
        raw = np.frombuffer(frames, dtype=np.uint8).reshape(-1, nch, 3)[start:end, 0, :]
        data = (raw[:, 0].astype(np.int32)
                | (raw[:, 1].astype(np.int32) << 8)
                | (raw[:, 2].astype(np.int32) << 16))
        data = data - (data >> 23) * (1 << 24)
        return rate, data.astype(np.float64) / (1 << 23)

    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(width)
    if dtype is None:
        raise ValueError(f"Unsupported WAV sample width: {width}")
    data = np.frombuffer(frames, dtype=dtype)
    if nch > 1:
        data = data.reshape(-1, nch)[:, 0]
    data = data[start:end]
    if width == 1:
        return rate, (data.astype(np.float64) - 128.0) / 128.0
    return rate, data.astype(np.float64) / (1 << (8 * width - 1))


def _read_wav_via_ffmpeg(path, start_time, end_time):
    """Convert an exotic WAV to 16-bit PCM with ffmpeg and read that."""
    fd, tmp_path = tempfile.mkstemp(suffix='.wav')
    os.close(fd)
    try:
        subprocess.run(
            ['ffmpeg', '-y', '-loglevel', 'error', '-i', path,
             '-acodec', 'pcm_s16le', tmp_path],
            check=True, timeout=60, capture_output=True)
        return _read_wav(tmp_path, start_time, end_time)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


@lru_cache(maxsize=1)
def _stft_window():
    import numpy as np
    win = np.hamming(_STFT_NPERSEG)
    return win, win.sum() ** 2


def _stft_spectrum(data, rate):
    """Power spectrogram, equivalent to scipy.signal.spectrogram(
    data, rate, window=hamming(nperseg), noverlap, nperseg,
    scaling='spectrum') with scipy defaults (detrend='constant', onesided).

    Returns (freqs_hz, Sxx) with Sxx shaped (freq_bins, time_frames).
    """
    import numpy as np

    nperseg, noverlap = _STFT_NPERSEG, _STFT_NOVERLAP
    if len(data) < nperseg:
        raise ValueError(
            f"Audio too short for spectrogram: {len(data)} < {nperseg} samples")
    win, win_scale = _stft_window()
    hop = nperseg - noverlap
    frames = np.lib.stride_tricks.sliding_window_view(data, nperseg)[::hop]
    frames = frames - frames.mean(axis=1, keepdims=True)  # detrend='constant'
    frames *= win
    spec = np.fft.rfft(frames, axis=1)
    Sxx = (spec.real ** 2 + spec.imag ** 2) / win_scale
    Sxx[:, 1:-1] *= 2  # fold negative frequencies (skip DC and Nyquist)
    freqs = np.fft.rfftfreq(nperseg, 1 / rate)
    return freqs, Sxx.T


def _nice_ticks(vmin, vmax):
    """Tick locations mimicking mpl AutoLocator on a short axis:
    steps 1/2/2.5/5 x 10^k, at most 4 intervals. With mag scaled to span/2,
    span/mag < 20, so step 5*mag always satisfies the bound."""
    span = vmax - vmin
    mag = 10 ** math.floor(math.log10(span / 2))
    for mult in (1, 2, 2.5, 5):
        step = mult * mag
        if span / step <= 4:
            break
    first = math.ceil(vmin / step) * step
    ticks = []
    t = first
    while t <= vmax + step / 2:
        ticks.append(int(t) if float(t).is_integer() else t)
        t += step
    return ticks


def _tick_y(value, vmin, vmax, box_top, box_bottom):
    """Pixel row for a tick: mpl centers ticks on the spine line, so the data
    range maps spine-center to spine-center, not across the box interior."""
    lo = box_bottom - _SPINE // 2
    hi = box_top + _SPINE // 2
    return round(lo - (value - vmin) / (vmax - vmin) * (lo - hi))


def generate_spectrogram(input_file_path, output_file_path, graph_title,
                         start_time=0, end_time=None):
    """Render a detection spectrogram WebP for a WAV file.

    Visual output matches the previous matplotlib renderer: absolute-dBFS
    Greens_r spectrogram panel with title, frequency axis, and intensity
    colorbar on a 1066x255 white canvas.
    """
    runtime = _get_render_runtime()
    import numpy as np
    from PIL import Image, ImageDraw

    fonts = runtime['fonts']
    lut = runtime['lut']

    spec_cfg = get_runtime_settings().get('spectrogram', {})
    max_dbfs = spec_cfg.get('max_dbfs', 0)      # absolute dBFS ceiling (0 = full scale)
    min_dbfs = spec_cfg.get('min_dbfs', -100)    # absolute dBFS floor / contrast knob
    max_freq_khz = spec_cfg.get('max_freq_khz', 12)
    min_freq_khz = spec_cfg.get('min_freq_khz', 0)
    if max_dbfs <= min_dbfs:
        max_dbfs = min_dbfs + 1
    if max_freq_khz <= min_freq_khz:
        max_freq_khz = min_freq_khz + 1

    rate, data = _read_wav(input_file_path, start_time, end_time)
    freqs, Sxx = _stft_spectrum(data, rate)

    # crop to the display band before the dB conversion — no point taking
    # log10 of bins the crop discards
    khz = freqs / 1000
    band = (khz >= min_freq_khz) & (khz <= max_freq_khz)
    if not band.any():
        band = np.ones_like(band)
    Sxx = Sxx[band]

    # Absolute dBFS referenced to a full-scale sine (power 0.5, hence *2),
    # matching the previous renderer: quiet clips render dim instead of
    # being auto-gained.
    Sxx_dbfs = 10 * np.log10(Sxx * 2 + 1e-10)

    norm = np.clip((Sxx_dbfs - min_dbfs) / (max_dbfs - min_dbfs), 0, 1)
    idx = (norm * 255).round().astype(np.uint8)
    rgb = lut[idx[::-1]]  # low freq at bottom

    img = Image.new('RGB', (_W, _H), 'white')
    draw = ImageDraw.Draw(img)

    # spectrogram panel (PIL rectangle coords are inclusive: interior of a
    # width-w border box spans (x1-x0+1) - 2w pixels)
    px0, py0, px1, py1 = _PANEL
    inner_w = px1 - px0 + 1 - 2 * _SPINE
    inner_h = py1 - py0 + 1 - 2 * _SPINE
    panel = Image.fromarray(rgb).resize((inner_w, inner_h), Image.BILINEAR)
    img.paste(panel, (px0 + _SPINE, py0 + _SPINE))
    draw.rectangle(_PANEL, outline='black', width=_SPINE)

    # title, centered over the panel
    title_w = draw.textlength(graph_title, font=fonts['title'])
    draw.text(((px0 + px1 - title_w) / 2, _TITLE_Y), graph_title,
              fill='black', font=fonts['title'])

    # frequency ticks: fixed 0/6/12 kHz, parity with the old renderer's
    # plt.yticks([0, 6, 12]); the colorbar uses _nice_ticks because its
    # range is user-configurable
    for tick in (0, 6, 12):
        if not (min_freq_khz <= tick <= max_freq_khz):
            continue
        y = _tick_y(tick, min_freq_khz, max_freq_khz, py0, py1)
        draw.line([(px0 - _TICK_LEN, y), (px0, y)], fill='black', width=_SPINE)
        label = str(tick)
        lw = draw.textlength(label, font=fonts['tick'])
        draw.text((px0 - _TICK_LEN - _TICK_PAD + _TICK_BEARING - lw,
                   y - _TICK_TEXT_DY), label, fill='black', font=fonts['tick'])

    ylabel = runtime['ylabel_mask']
    img.paste((0, 0, 0), (px0 - 72, (py0 + py1) // 2 - ylabel.height // 2), ylabel)

    # colorbar
    cx0, cy0, cx1, cy1 = _CBAR
    img.paste(runtime['cbar_gradient'], (cx0 + _SPINE, cy0 + _SPINE))
    draw.rectangle(_CBAR, outline='black', width=_SPINE)

    ticks = _nice_ticks(min_dbfs, max_dbfs)
    labels = [f'{t:g}'.replace('-', _MINUS) for t in ticks]
    label_x = cx1 + _TICK_LEN + _TICK_PAD - _TICK_BEARING
    for tick, label in zip(ticks, labels, strict=True):
        y = _tick_y(tick, min_dbfs, max_dbfs, cy0, cy1)
        draw.line([(cx1, y), (cx1 + _TICK_LEN, y)], fill='black', width=_SPINE)
        draw.text((label_x, y - _TICK_TEXT_DY), label, fill='black',
                  font=fonts['tick'])

    widest = max(draw.textlength(s, font=fonts['tick']) for s in labels)
    clabel = runtime['clabel_mask']
    img.paste((0, 0, 0), (int(label_x + widest - 1),
                          (cy0 + cy1) // 2 - clabel.height // 2), clabel)

    img.save(output_file_path, 'WEBP', quality=85)
