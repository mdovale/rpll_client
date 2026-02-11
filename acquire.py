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

import sys
import socket
import struct
import time
from typing import Optional, List, Callable

import frame_schema
import rp_protocol


def check_frame_corruption(output: List[float]) -> tuple:
    """
    Check if unpacked frame data is corrupted (negative FFT bins or tail-as-FFT).

    Parameters
    ----------
    output : list of float
        Unpacked frame (FRAME_SIZE_DOUBLES doubles).

    Returns
    -------
    tuple of (bool, int, float)
        (corrupted, neg_bins, fft_max).
        corrupted is True when neg_bins > 10 or fft_max > 1e6.
    """
    neg_bins = 0
    fft_max = 0.0
    fft_data_end = (
        frame_schema.FFT_RESULT_CHAN1_START + 2 * frame_schema.FFT_SIZE
    )
    for v in output[frame_schema.FFT_RESULT_CHAN1_START:fft_data_end]:
        if v < -1e-9:
            neg_bins += 1
        if v > fft_max:
            fft_max = v
    corrupted = neg_bins > 10 or fft_max > 1e6
    return (corrupted, neg_bins, fft_max)


class RPConnection:
    """Owns the socket and RX buffer for RedPitaya TCP connection.
    
    API: connect(ip, port), disconnect(), read_frame(timeout_s=0.0),
    is_connected, last_read_status, .socket for sending commands.
    """

    def __init__(self) -> None:
        """Initialize connection state (disconnected, no buffer)."""
        self._socket: Optional[socket.socket] = None
        self._rxbuf = bytearray()
        self._warned_corruption = False
        self.last_read_status: str = "no_socket"
        # Default to the reduced/safer UI until server explicitly advertises laser_lock.
        self._server_variant: str = rp_protocol.RP_CAP_PHASEMETER
        self._capability_line: Optional[str] = None
        self._log_callback: Optional[Callable[[str], None]] = None

    def set_log_callback(self, cb: Optional[Callable[[str], None]]) -> None:
        """Set optional callback for warnings (e.g. GUI log). Called with message str."""
        self._log_callback = cb

    @property
    def socket(self) -> Optional[socket.socket]:
        """
        Socket used for TCP communication with the RedPitaya.

        Returns
        -------
        socket.socket or None
            The connected socket, or None if disconnected.
        """
        return self._socket

    def is_connected(self) -> bool:
        """
        Report whether a connection is currently open.

        Returns
        -------
        bool
            True if connected, False otherwise.
        """
        return self._socket is not None

    @property
    def server_variant(self) -> str:
        """
        Server capability: 'laser_lock' (full) or 'phasemeter' (readout only).

        Set during connect from the capability handshake. Defaults to
        'phasemeter' if handshake fails or server is older.
        """
        return self._server_variant

    @property
    def capability_line(self) -> Optional[str]:
        """
        Raw capability line received from server, or None if absent.

        When present, this is the decoded line without the trailing newline.
        """
        return self._capability_line

    def set_server_variant(self, variant: str) -> None:
        """
        Override the detected server variant.

        Parameters
        ----------
        variant : str
            Either RP_CAP_PHASEMETER or RP_CAP_LASER_LOCK.
        """
        if variant in (rp_protocol.RP_CAP_PHASEMETER, rp_protocol.RP_CAP_LASER_LOCK):
            self._server_variant = variant

    def connect(self, ip: str, port: int, timeout_s: float = 0.5) -> None:
        """
        Connect to the RedPitaya and send init commands.

        Parameters
        ----------
        ip : str
            IPv4 address of the RedPitaya.
        port : int
            TCP port (typically 1001).
        timeout_s : float, optional
            Timeout for the connect and init phase, in seconds. Default is 0.5.

        Raises
        ------
        OSError
            On connection failure or timeout.
        """
        address = (ip, port)
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.settimeout(timeout_s)
        client_socket.connect(address)

        # Read capability handshake: "RP_CAP:laser_lock\n" or "RP_CAP:phasemeter\n"
        # Default to phasemeter until an explicit capability line advertises laser_lock.
        self._server_variant = rp_protocol.RP_CAP_PHASEMETER
        self._capability_line = None
        client_socket.settimeout(1.0)
        try:
            buf = bytearray()
            while len(buf) < rp_protocol.RP_CAP_LINE_MAX:
                chunk = client_socket.recv(1)
                if not chunk:
                    break
                if chunk == b"\n":
                    line = buf.decode("ascii", errors="replace").strip()
                    self._capability_line = line
                    if line.startswith(rp_protocol.RP_CAP_PREFIX):
                        variant = line[len(rp_protocol.RP_CAP_PREFIX) :].strip()
                        if variant == rp_protocol.RP_CAP_PHASEMETER:
                            self._server_variant = rp_protocol.RP_CAP_PHASEMETER
                        elif variant == rp_protocol.RP_CAP_LASER_LOCK:
                            self._server_variant = rp_protocol.RP_CAP_LASER_LOCK
                    break
                buf.extend(chunk)
        except (OSError, UnicodeDecodeError, socket.timeout):
            pass

        cmd1 = struct.pack("<I", int("01000001", 16))
        cmd2 = struct.pack("<I", int("00000001", 16))
        client_socket.send(cmd1)
        time.sleep(0.05)

        client_socket.send(cmd2)
        time.sleep(0.05)

        client_socket.settimeout(None)
        self._socket = client_socket
        self._rxbuf = bytearray()
        self._warned_corruption = False
        self.last_read_status = "no_data"

    def disconnect(self) -> None:
        """
        Close the socket and clear the receive buffer.

        Safe to call when already disconnected. Sets last_read_status to "no_socket".

        Returns
        -------
        None
        """
        s = self._socket
        self._socket = None
        self._rxbuf = bytearray()
        self._warned_corruption = False
        self._server_variant = rp_protocol.RP_CAP_PHASEMETER
        self._capability_line = None
        self.last_read_status = "no_socket"
        if s is None:
            return
        try:
            s.close()
        except Exception:
            pass

    def read_frame(
        self, timeout_s: float = 0.0, suppress_corruption_warning: bool = False
    ) -> Optional[List[float]]:
        """
        Read one full frame from the socket.

        Parameters
        ----------
        timeout_s : float, optional
            If > 0, wait up to this many seconds for a full frame. If 0, non-blocking.
            Default is 0.0.
        suppress_corruption_warning : bool, optional
            If True, do not log the desync warning when realigning. Use when
            intentionally discarding frames after reconnect. Default is False.

        Returns
        -------
        list of float or None
            One frame of FRAME_SIZE_DOUBLES doubles, or None if no frame available
            or on error. Updates last_read_status ("ok", "no_data", "timeout",
            "closed", "parse_error", "os_error", "no_socket").
        """
        if self._socket is None:
            self.last_read_status = "no_socket"
            return None

        prev_timeout = self._socket.gettimeout()
        self.last_read_status = "no_data"

        def warn_once(msg: str) -> None:
            if self._warned_corruption:
                return
            self._warned_corruption = True
            try:
                print(msg, file=sys.stderr)
            except Exception:
                pass
            if self._log_callback:
                try:
                    self._log_callback(msg)
                except Exception:
                    pass

        try:
            self._socket.settimeout(timeout_s if timeout_s and timeout_s > 0 else 0.0)

            # Frame alignment: on corruption (misaligned stream), discard 1 byte and retry.
            align_discard = 0
            max_align_discard = frame_schema.FRAME_SIZE_BYTES

            while align_discard <= max_align_discard:
                if timeout_s and timeout_s > 0:
                    while len(self._rxbuf) < frame_schema.FRAME_SIZE_BYTES:
                        try:
                            chunk = self._socket.recv(
                                frame_schema.FRAME_SIZE_BYTES - len(self._rxbuf)
                            )
                        except socket.timeout:
                            self.last_read_status = "timeout"
                            return None
                        if not chunk:
                            self.last_read_status = "closed"
                            return None
                        self._rxbuf += chunk
                else:
                    while True:
                        try:
                            chunk = self._socket.recv(64 * 1024)
                        except (BlockingIOError, InterruptedError):
                            break
                        except socket.timeout:
                            break
                        if not chunk:
                            self.last_read_status = "closed"
                            return None
                        self._rxbuf += chunk
                        if len(self._rxbuf) > frame_schema.FRAME_SIZE_BYTES * 4:
                            del self._rxbuf[:-frame_schema.FRAME_SIZE_BYTES * 2]

                if len(self._rxbuf) < frame_schema.FRAME_SIZE_BYTES:
                    self.last_read_status = "no_data"
                    return None

                raw = bytes(self._rxbuf[:frame_schema.FRAME_SIZE_BYTES])
                output = struct.unpack(f"{frame_schema.FRAME_SIZE_DOUBLES}d", raw)

                corrupted, neg_bins, fft_max = check_frame_corruption(output)
                if corrupted:
                    if align_discard == 0 and not suppress_corruption_warning:
                        warn_once(
                            "Warning: frame desynchronized (neg_bins=%d, fft_max=%.2e); "
                            "realigning..."
                            % (neg_bins, fft_max)
                        )
                    del self._rxbuf[:1]
                    align_discard += 1
                    continue

                del self._rxbuf[:frame_schema.FRAME_SIZE_BYTES]
                self.last_read_status = "ok"
                return list(output)

            self.last_read_status = "parse_error"
            return None
        except struct.error:
            self.last_read_status = "parse_error"
            return None
        except OSError:
            self.last_read_status = "os_error"
            return None
        finally:
            try:
                self._socket.settimeout(prev_timeout)
            except Exception:
                pass


# Legacy API: module-level state for readRPdata/clear_rxbuf when using raw socket.
def connect2RP(ip, port, timeout_s=0.5):
    """
    Connect to the RedPitaya and return a raw socket (legacy API).

    Prefer RPConnection.connect() for new code.

    Parameters
    ----------
    ip : str
        IPv4 address of the RedPitaya.
    port : int
        TCP port (typically 1001).
    timeout_s : float, optional
        Timeout for connect and init, in seconds. Default is 0.5.

    Returns
    -------
    socket.socket
        Connected socket after sending init commands.

    Raises
    ------
    OSError
        On connection failure or timeout.
    """
    address = (ip,port) # TCP address = IP + port
    client_socket = socket.socket(socket.AF_INET,socket.SOCK_STREAM) # Creation of the client socket.
    client_socket.settimeout(timeout_s)
    client_socket.connect(address) # Connection of the client_socket using the address information

    # Sending the right commands to the RP so it starts sending data
    # These commands are interpreted by the RP and used for initial configuration.
    
    # The first one is a reset with argument '01' to register '1'
    # Sending the command to the RP via the socket. The weird two-lines step below is needed to compensate for the enconding of the hex data in the RP
    command=int("01000001",16)
    commandInv=struct.pack("<I",command) # unsigned Int to object ('hex string') using little Endian
    client_socket.send(commandInv)
    time.sleep(0.05) # The short sleep is necessary between commands to avoid mixing information on the receiving end.



    # Sending the command to the RP via the socket. The weird two-lines step below is needed to compensate for the enconding of the hex data in the RP
    command=int("00000001",16)
    commandInv=struct.pack("<I",command) # unsigned Int to object ('hex string') using little Endian
    client_socket.send(commandInv)
    time.sleep(0.05) # The short sleep is necessary between commands to avoid mixing information on the receiving end.

    # It returns the client_socket so that it can be used aftewards to modify the settings of the different registers
    # Switch back to blocking mode; reads can still use per-call timeouts.
    client_socket.settimeout(None)
    return client_socket






def readRPdata(client_socket, timeout_s=0.0):
    """
    Read one full frame from the socket (legacy API).

    Uses module-level state for per-socket RX buffers. Sets readRPdata.last_status.
    Prefer RPConnection.read_frame() for new code.

    Parameters
    ----------
    client_socket : socket.socket or None
        Connected TCP socket, or None (returns None immediately).
    timeout_s : float, optional
        If > 0, wait up to this many seconds for a full frame. If 0, non-blocking.
        Default is 0.0.

    Returns
    -------
    list of float or None
        One frame of doubles, or None. Check readRPdata.last_status for reason.
    """
    output=[]
    if client_socket is None:
        readRPdata.last_status = "no_socket"
        return None

    # Keep per-socket receive buffers so partial frames aren't lost between calls.
    # Key by fileno to avoid keeping sockets alive unintentionally.
    if not hasattr(readRPdata, "_rxbuf_by_fileno"):
        readRPdata._rxbuf_by_fileno = {}
    if not hasattr(readRPdata, "_warned_corruption"):
        readRPdata._warned_corruption = False

    prev_timeout = client_socket.gettimeout()
    fileno = client_socket.fileno()
    readRPdata.last_status = "no_data"
    rxbuf = readRPdata._rxbuf_by_fileno.get(fileno)
    if rxbuf is None:
        rxbuf = bytearray()
        readRPdata._rxbuf_by_fileno[fileno] = rxbuf

    def warn_once(msg: str) -> None:
        if readRPdata._warned_corruption:
            return
        readRPdata._warned_corruption = True
        try:
            print(msg, file=sys.stderr)
        except Exception:
            pass

    # Read and accumulate bytes:
    # - If timeout_s == 0.0: non-blocking; read whatever is available now.
    # - If timeout_s  > 0.0: wait up to timeout_s until at least one full frame is available.
    try:
        client_socket.settimeout(timeout_s if timeout_s and timeout_s > 0 else 0.0)

        if timeout_s and timeout_s > 0:
            # Bounded wait until we have at least one full frame.
            while len(rxbuf) < frame_schema.FRAME_SIZE_BYTES:
                try:
                    chunk = client_socket.recv(frame_schema.FRAME_SIZE_BYTES - len(rxbuf))
                except socket.timeout:
                    readRPdata.last_status = "timeout"
                    return None
                if not chunk:
                    readRPdata.last_status = "closed"
                    return None
                rxbuf += chunk
        else:
            # Non-blocking: drain available bytes quickly.
            while True:
                try:
                    chunk = client_socket.recv(64 * 1024)
                except (BlockingIOError, InterruptedError):
                    readRPdata.last_status = "no_data"
                    break
                except socket.timeout:
                    readRPdata.last_status = "no_data"
                    break
                if not chunk:
                    readRPdata.last_status = "closed"
                    return None
                rxbuf += chunk
                # Avoid unbounded growth if we were desynced; keep only the newest few frames.
                if len(rxbuf) > frame_schema.FRAME_SIZE_BYTES * 4:
                    del rxbuf[:-frame_schema.FRAME_SIZE_BYTES * 2]

        if len(rxbuf) < frame_schema.FRAME_SIZE_BYTES:
            readRPdata.last_status = "no_data"
            return None

        raw = bytes(rxbuf[:frame_schema.FRAME_SIZE_BYTES])
        del rxbuf[:frame_schema.FRAME_SIZE_BYTES]

        output = struct.unpack(f"{frame_schema.FRAME_SIZE_DOUBLES}d", raw)

        # Minimal sanity check: FFT magnitudes are expected to be >= 0.
        # Allow tiny numerical noise, but not large negative values across many bins.
        neg_bins = 0
        fft_data_end = frame_schema.FFT_RESULT_CHAN1_START + 2 * frame_schema.FFT_SIZE
        for v in output[frame_schema.FFT_RESULT_CHAN1_START:fft_data_end]:
            if v < -1e-9:
                neg_bins += 1
                if neg_bins > 10:
                    warn_once(
                        "Warning: received a frame with many negative FFT magnitudes; "
                        "stream may be corrupted or desynchronized."
                    )
                    break

        readRPdata.last_status = "ok"
        return list(output)
    except struct.error:
        readRPdata.last_status = "parse_error"
        return None
    except OSError:
        readRPdata.last_status = "os_error"
        return None
    finally:
        try:
            client_socket.settimeout(prev_timeout)
        except Exception:
            pass


def clear_rxbuf(client_socket) -> None:
    """
    Forget any partially buffered bytes for this socket (legacy API).

    Cleans up the per-socket buffer used by readRPdata. Safe to call with
    invalid socket; ignores exceptions.

    Parameters
    ----------
    client_socket : socket.socket
        Socket whose buffer should be cleared (identified by fileno).
    """
    try:
        fileno = client_socket.fileno()
    except Exception:
        return
    rxbufs = getattr(readRPdata, "_rxbuf_by_fileno", None)
    if not isinstance(rxbufs, dict):
        return
    rxbufs.pop(fileno, None)



# When run directly: connect and read frames (for debugging).
if __name__ == "__main__":
    conn = RPConnection()
    conn.connect("192.168.2.124", 1001)
    try:
        while True:
            output = conn.read_frame()
            print(output)
            print("\n")
    finally:
        conn.disconnect()
