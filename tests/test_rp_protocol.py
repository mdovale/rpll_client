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

"""Tests for rp_protocol encoding (no socket)."""
import struct
import pytest
import rp_protocol


def test_pack_register_write():
    payload = rp_protocol.pack_register_write("03", 0x12345678)
    assert len(payload) == 8
    a, b = struct.unpack("<II", payload)
    assert a == 0x03000000
    assert b == 0x12345678


def test_pack_reset():
    hold = rp_protocol.pack_reset(release=False)
    assert len(hold) == 4
    assert struct.unpack("<I", hold)[0] == 0x01000000
    release = rp_protocol.pack_reset(release=True)
    assert len(release) == 4
    assert struct.unpack("<I", release)[0] == 0x01000001


def test_scaled_value_to_int():
    # factor * display_value = 0.000032768 * 1000 = 0.032768 -> int 0
    assert rp_protocol.scaled_value_to_int(1000.0, 0.000032768) == 0
    # 1000000 * 0.000032768 = 32.768 -> int 32
    assert rp_protocol.scaled_value_to_int(1000000.0, 0.000032768) == 32


def test_offset_float_to_int():
    assert rp_protocol.offset_float_to_int(0.0) == 0
    assert rp_protocol.offset_float_to_int(1.0) == 8192  # 2^13
    neg = rp_protocol.offset_float_to_int(-0.5)
    assert neg == (2**14) + int(-0.5 * (2**13))
