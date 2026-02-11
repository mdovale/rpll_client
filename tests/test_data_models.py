"""
BSD 3-Clause License

Copyright (c) 2026, Miguel Dovale (University of Arizona)

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

This software may be subject to U.S. export control laws. By accepting this
software, the user agrees to comply with all applicable U.S. export laws and
regulations. User has the responsibility to obtain export licenses, or other
export authority as may be required before exporting such information to
foreign countries or providing access to foreign persons.
"""

"""Tests for DataPackage.parse_frame and build_plot_view_model (no Qt)."""
import numpy as np
import pytest
import frame_schema
import global_params as glp
from data_models import (
    DataPackage,
    Frame,
    PlotViewModel,
    build_plot_view_model,
    effective_beatfreq,
)


def test_parse_frame_rejects_none():
    assert DataPackage.parse_frame(None) is None


def test_parse_frame_rejects_wrong_length():
    short = [0.0] * 100
    assert DataPackage.parse_frame(short) is None
    long_list = [0.0] * 3000
    assert DataPackage.parse_frame(long_list) is None


def test_parse_frame_returns_frame():
    raw = [0.0] * frame_schema.FRAME_SIZE_DOUBLES
    raw[frame_schema.FRAME_COUNTER] = 42.0
    raw[frame_schema.PLL0PIR] = 1.5e6
    raw[frame_schema.PLL1PIR] = 2.0e6
    raw[frame_schema.FFT_RESULT_CHAN1_START] = 0.1
    frame = DataPackage.parse_frame(raw)
    assert frame is not None
    assert frame.cnt == 42
    assert frame.pir[0] == 1.5e6
    assert frame.pir[1] == 2.0e6
    assert len(frame.spectrum[0]) == frame_schema.FFT_SIZE
    assert frame.spectrum[0][0] == pytest.approx(0.1 * glp.ABS_CAL_FACTOR)


def test_build_plot_view_model():
    dataset = DataPackage()
    dataset.f[0] = 1.0
    dataset.spectrum[0][0] = 2.0
    vm = build_plot_view_model(dataset)
    assert isinstance(vm, PlotViewModel)
    assert vm.f is dataset.f
    assert vm.spectrum is dataset.spectrum
    assert vm.beatfreq is dataset.beatfreq
    assert vm.t is dataset.t
    assert vm.i_t is dataset.i_t
    assert vm.freq_plot_t is dataset.freqerr_t


def test_spectrum_frequency_axis_matches_fft_bins():
    """Spectrum f-axis: bin k at k*125e6/1024 Hz (matches server FFT)."""
    dataset = DataPackage()
    f = dataset.f
    assert len(f) == 513
    assert f[0] == 0.0
    assert f[1] == pytest.approx(125e6 / 1024)
    assert f[512] == pytest.approx(62.5e6)  # Nyquist


def test_effective_beatfreq_server_zero_uses_argmax():
    """When server sends beatfreq=0 but spectrum has peak, use argmax fallback."""
    f = np.arange(513, dtype=float) * 125e6 / 1024
    spec = np.zeros(513)
    spec[100] = 0.1
    r, used_fallback = effective_beatfreq(spec, 0.0, f)
    assert r > 0
    assert r == pytest.approx(f[100])
    assert used_fallback is True


def test_effective_beatfreq_server_valid_used():
    """When server sends valid beatfreq >= 1kHz and spectrum has no peak, use it."""
    f = np.arange(513, dtype=float) * 125e6 / 1024
    spec = np.zeros(513)  # no peak -> argmax_freq=0, we use server
    r, used_fallback = effective_beatfreq(spec, 20e6, f)
    assert r == 20e6
    assert used_fallback is False


def test_effective_beatfreq_server_valid_matches_spectrum():
    """When server value matches spectrum argmax, use server (no fallback)."""
    f = np.arange(513, dtype=float) * 125e6 / 1024
    spec = np.zeros(513)
    spec[100] = 0.1  # peak at f[100] ~= 12.2 MHz
    server_val = f[100]
    r, used_fallback = effective_beatfreq(spec, server_val, f)
    assert r == pytest.approx(server_val)
    assert used_fallback is False


def test_effective_beatfreq_cross_check_wrong_server():
    """When server value disagrees strongly with spectrum argmax, prefer argmax."""
    f = np.arange(513, dtype=float) * 125e6 / 1024
    spec = np.zeros(513)
    spec[100] = 0.1  # peak at ~12.2 MHz
    r, used_fallback = effective_beatfreq(spec, 80e6, f, max_discrepancy_hz=2e6)
    assert abs(r - f[100]) < 1e6
    assert used_fallback is True


def test_effective_beatfreq_empty_spectrum_returns_zero():
    """When spectrum is empty, return 0 and used_fallback=True."""
    f = np.arange(513, dtype=float) * 125e6 / 1024
    spec = np.array([])
    r, used_fallback = effective_beatfreq(spec, 0.0, f)
    assert r == 0.0
    assert used_fallback is True


def test_effective_beatfreq_spectrum_below_threshold_returns_zero():
    """When spectrum max < spec_thresh, return 0."""
    f = np.arange(513, dtype=float) * 125e6 / 1024
    spec = np.zeros(513)
    spec[100] = 1e-8  # below default spec_thresh 1e-5
    r, used_fallback = effective_beatfreq(spec, 0.0, f, spec_thresh=1e-5)
    assert r == 0.0
    assert used_fallback is True


def test_datapackage_substitute_data_raw():
    """substitute_data accepts raw list and updates dataset."""
    dp = DataPackage()
    raw = [0.0] * frame_schema.FRAME_SIZE_DOUBLES
    raw[frame_schema.FRAME_COUNTER] = 99.0
    raw[frame_schema.PLL0PIR] = 5e6
    raw[frame_schema.MAX_ABS_FREQ0] = 10e6
    dp.substitute_data(raw)
    assert dp.cnt == 99
    assert dp.pir[0] == 5e6
    assert dp.beatfreq[0] == 10e6


def test_datapackage_clear():
    """clear resets all data to zeros/empty."""
    dp = DataPackage()
    dp.cnt = 42
    dp.spectrum[0][0] = 1.0
    dp.beatfreq[0] = 10e6
    dp.clear()
    assert dp.cnt == 0
    assert dp.spectrum[0][0] == 0.0
    assert dp.beatfreq[0] == 0.0
