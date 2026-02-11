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
Frame layout schema for RedPitaya data frames.

This module defines the binary frame format used for communication between
the Python GUI and the RedPitaya server. The frame layout must match
`server/esw/memory_map.h::FRAME_CONTENT_ADDRESS_OFFSET`.

Frame format:
- FFT_SIZE = 513 (defined in `server/esw/fft_peak.h`)
- FRAME_SIZE = (2*FFT_SIZE+16) doubles = 1042 doubles
- FRAME_SIZE_BYTES = 1042 * 8 = 8336 bytes

Frame content (as indices into the unpacked list of doubles):
- [0]: FRAME_COUNTER
- [1:514]: FFT_RESULT_CHAN1_START (513 values)
- [514:1027]: FFT_RESULT_CHAN2_START (513 values)
- [1028]: PLL0PIR
- [1029]: PLL1PIR
- [1030]: PLL0Q
- [1031]: PLL1Q
- [1032]: PLL0I
- [1033]: PLL1I
- [1034]: PIEZO_ACT0
- [1035]: PIEZO_ACT1
- [1036]: TEMP_ACT0
- [1037]: TEMP_ACT1
- [1038]: FREQ_ERR0
- [1039]: FREQ_ERR1
- [1040]: MAX_ABS_FREQ0 (beatfreq[0])
- [1041]: MAX_ABS_FREQ1 (beatfreq[1])
"""

# FFT_SIZE must match `server/esw/fft_peak.h`
FFT_SIZE = 513

# Frame size constants (must match `server/esw/memory_map.h`)
FRAME_SIZE_DOUBLES = 2 * FFT_SIZE + 16  # 1042
FRAME_SIZE_BYTES = FRAME_SIZE_DOUBLES * 8  # 8336

# Frame content offsets (must match `server/esw/memory_map.h::FRAME_CONTENT_ADDRESS_OFFSET`)
FRAME_COUNTER = 0
FFT_RESULT_CHAN1_START = 1
FFT_RESULT_CHAN2_START = 1 + FFT_SIZE  # 514
TAIL_START = 2 * FFT_SIZE + 2  # 1028

# Tail field offsets (relative to start of frame, i.e., absolute indices)
PLL0PIR = TAIL_START  # 1028
PLL1PIR = TAIL_START + 1  # 1029
PLL0Q = TAIL_START + 2  # 1030
PLL1Q = TAIL_START + 3  # 1031
PLL0I = TAIL_START + 4  # 1032
PLL1I = TAIL_START + 5  # 1033
PIEZO_ACT0 = TAIL_START + 6  # 1034
PIEZO_ACT1 = TAIL_START + 7  # 1035
TEMP_ACT0 = TAIL_START + 8  # 1036
TEMP_ACT1 = TAIL_START + 9  # 1037
FREQ_ERR0 = TAIL_START + 10  # 1038
FREQ_ERR1 = TAIL_START + 11  # 1039
MAX_ABS_FREQ0 = TAIL_START + 12  # 1040
MAX_ABS_FREQ1 = TAIL_START + 13  # 1041
