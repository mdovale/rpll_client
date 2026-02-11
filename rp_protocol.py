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

"""
RedPitaya TCP command protocol.

Encodes register writes and reset commands for the RP server.
Command format must match what the server expects (see server/esw/server.c).

Capability handshake: server sends "RP_CAP:<variant>\\n" on connect.
Variant: "laser_lock" (full) or "phasemeter" (readout only).
"""
RP_CAP_PREFIX = "RP_CAP:"
RP_CAP_LASER_LOCK = "laser_lock"
RP_CAP_PHASEMETER = "phasemeter"
RP_CAP_LINE_MAX = 32

import struct
from typing import Optional


def pack_register_write(register_hex: str, value: int) -> bytes:
    """
    Encode a register write as 8 bytes (two little-endian uint32).

    Parameters
    ----------
    register_hex : str
        Register ID as hex string, e.g. '03', '0A'.
    value : int
        32-bit value to send (masked to 0xFFFFFFFF).

    Returns
    -------
    bytes
        8-byte payload: (register_id << 24) | value, little-endian.
    """
    cmd_a = int(register_hex + "000000", 16)
    return struct.pack("<II", cmd_a, value & 0xFFFFFFFF)


def pack_reset(release: bool) -> bytes:
    """
    Encode reset command (hold or release) as 4 bytes.

    Parameters
    ----------
    release : bool
        If True, encode release (0x01000001); if False, hold (0x01000000).

    Returns
    -------
    bytes
        4-byte payload, little-endian.
    """
    command = int("01" + ("000001" if release else "000000"), 16)
    return struct.pack("<I", command)


def scaled_value_to_int(display_value: float, factor: float) -> int:
    """
    Encode display value for a scaled register (e.g. frequency).

    Parameters
    ----------
    display_value : float
        Value shown in the UI (e.g. Hz).
    factor : float
        Scale factor to convert to register units.

    Returns
    -------
    int
        int(factor * display_value).
    """
    return int(factor * display_value)


def offset_float_to_int(display_value: float) -> int:
    """
    Encode offset in [-0.99, 0.99] as 14-bit signed then 32-bit.

    Parameters
    ----------
    display_value : float
        Offset value (e.g. -0.5 to 0.5).

    Returns
    -------
    int
        value * 2^13; if negative, 2^14 + value (two's complement).
    """
    temp = int(display_value * (2**13))
    if temp < 0:
        temp = (2**14) + temp
    return temp


def send_register_write(socket, register_hex: str, value: int) -> None:
    """
    Encode and send a register write on the given socket.

    Parameters
    ----------
    socket : socket.socket or None
        TCP socket to the RedPitaya. If None, no-op.
    register_hex : str
        Register ID as hex string.
    value : int
        32-bit value to send.
    """
    if socket is None:
        return
    socket.send(pack_register_write(register_hex, value))


def send_reset(socket, release: bool) -> None:
    """
    Encode and send reset command (hold or release) on the given socket.

    Parameters
    ----------
    socket : socket.socket or None
        TCP socket to the RedPitaya. If None, no-op.
    release : bool
        If True, send release; if False, send hold.
    """
    if socket is None:
        return
    socket.send(pack_reset(release))
