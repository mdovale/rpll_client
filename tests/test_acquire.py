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
"""

"""Tests for acquire.check_frame_corruption and RPConnection (no socket)."""
import pytest
import frame_schema
from acquire import check_frame_corruption, RPConnection


def _make_frame(fft_ch1=None, fft_ch2=None, tail_start=2050):
    """Build a valid-sized frame of zeros, optionally fill FFT regions."""
    out = [0.0] * frame_schema.FRAME_SIZE_DOUBLES
    if fft_ch1 is not None:
        for i, v in enumerate(fft_ch1):
            if frame_schema.FFT_RESULT_CHAN1_START + i < len(out):
                out[frame_schema.FFT_RESULT_CHAN1_START + i] = v
    if fft_ch2 is not None:
        for i, v in enumerate(fft_ch2):
            if frame_schema.FFT_RESULT_CHAN2_START + i < len(out):
                out[frame_schema.FFT_RESULT_CHAN2_START + i] = v
    return out


def test_check_frame_corruption_valid_frame():
    """Valid frame: all FFT magnitudes small and non-negative."""
    out = _make_frame(
        fft_ch1=[0.01] * frame_schema.FFT_SIZE,
        fft_ch2=[0.02] * frame_schema.FFT_SIZE,
    )
    corrupted, neg_bins, fft_max = check_frame_corruption(out)
    assert corrupted is False
    assert neg_bins == 0
    assert fft_max == 0.02


def test_check_frame_corruption_many_negative_bins():
    """Frame with >10 negative FFT bins is corrupted."""
    out = _make_frame(fft_ch1=[0.0] * frame_schema.FFT_SIZE)
    for i in range(15):
        out[frame_schema.FFT_RESULT_CHAN1_START + i] = -0.1
    corrupted, neg_bins, fft_max = check_frame_corruption(out)
    assert corrupted is True
    assert neg_bins == 15


def test_check_frame_corruption_huge_fft_magnitude():
    """Frame with fft_max > 1e6 (tail-as-FFT) is corrupted."""
    out = _make_frame(fft_ch1=[0.0] * frame_schema.FFT_SIZE)
    out[frame_schema.FFT_RESULT_CHAN1_START + 100] = 9.98e6  # PIR-like value
    corrupted, neg_bins, fft_max = check_frame_corruption(out)
    assert corrupted is True
    assert fft_max == 9.98e6


def test_check_frame_corruption_few_negative_bins_ok():
    """Up to 10 negative bins is still accepted."""
    out = _make_frame(fft_ch1=[0.0] * frame_schema.FFT_SIZE)
    for i in range(10):
        out[frame_schema.FFT_RESULT_CHAN1_START + i] = -0.1
    corrupted, neg_bins, fft_max = check_frame_corruption(out)
    assert corrupted is False
    assert neg_bins == 10


def test_check_frame_corruption_fft_max_just_under_threshold():
    """fft_max just under 1e6 is accepted."""
    out = _make_frame(fft_ch1=[0.0] * frame_schema.FFT_SIZE)
    out[frame_schema.FFT_RESULT_CHAN1_START + 50] = 5e5
    corrupted, neg_bins, fft_max = check_frame_corruption(out)
    assert corrupted is False
    assert fft_max == 5e5


def test_rpconnection_read_frame_no_socket():
    """read_frame returns None when not connected."""
    conn = RPConnection()
    assert conn.read_frame(timeout_s=0.0) is None
    assert conn.last_read_status == "no_socket"


def test_rpconnection_set_log_callback():
    """set_log_callback stores callback for use when frame corruption is detected."""
    conn = RPConnection()
    log = []
    conn.set_log_callback(lambda msg: log.append(msg))
    conn._log_callback("test")
    assert log == ["test"]
