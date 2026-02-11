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

import numpy as np
from dataclasses import dataclass
from typing import Optional, List, Union
import global_params as glp
import frame_schema


def update_data_t(array, data):
	"""
	Append one sample to the end of a 1D array and drop the first element.

	Parameters
	----------
	array : numpy.ndarray
		One-dimensional array (modified in place via reassignment).
	data : scalar or array-like
		Value(s) to append.

	Returns
	-------
	numpy.ndarray
		New array of same length: [array[1:], data].
	"""
	array = np.append(array, data)
	array = np.delete(array, 0)
	return array

def update_data_t2(array, data):
	"""
	Update two 1D time-series arrays with new samples (rolling window).

	Parameters
	----------
	array : list of two numpy.ndarray
		[channel0_series, channel1_series].
	data : array-like of length 2
		[channel0_sample, channel1_sample].

	Returns
	-------
	list of two numpy.ndarray
		The updated arrays (same structure as array).
	"""
	array[0] = update_data_t(array[0], data[0])
	array[1] = update_data_t(array[1], data[1])
	return array


@dataclass
class Frame:
	"""Parsed frame data from RedPitaya.
	
	This represents a single frame's parsed content. All frame parsing
	logic is encapsulated in DataPackage.parse_frame().
	"""
	cnt: int
	spectrum: List[np.ndarray]  # [channel0, channel1], each FFT_SIZE floats
	pir: np.ndarray  # [channel0, channel1]
	q: np.ndarray  # [channel0, channel1]
	i: np.ndarray  # [channel0, channel1]
	piezo: np.ndarray  # [channel0, channel1]
	temp: np.ndarray  # [channel0, channel1]
	freqerr: np.ndarray  # [channel0, channel1]
	beatfreq: np.ndarray  # [channel0, channel1]


@dataclass
class PlotViewModel:
	"""Minimal data for updating plots. Built from DataPackage so gui.py does not depend on dataset structure."""
	f: np.ndarray  # Fourier frequencies
	spectrum: List[np.ndarray]  # [channel0, channel1]
	pir: np.ndarray  # [channel0, channel1]
	beatfreq: np.ndarray  # [channel0, channel1] FFT peak frequencies (Hz)
	t: np.ndarray  # time axis
	i_t: List[np.ndarray]
	q_t: List[np.ndarray]
	freqerr_t: List[np.ndarray]
	freq_plot_t: List[np.ndarray]
	piezo_t: List[np.ndarray]
	temp_t: List[np.ndarray]


_HEALTH_GREEN = "green"
_HEALTH_YELLOW = "yellow"
_HEALTH_RED = "red"


@dataclass
class HealthSnapshot:
	"""Aggregated health indicators for the top bar."""
	fft: str
	i_value: str
	q_value: str
	freq_readout: str
	freq_error: str
	ctrl: str


def _combine_health(levels: List[str]) -> str:
	"""Return the worst health level in a list (red > yellow > green)."""
	if _HEALTH_RED in levels:
		return _HEALTH_RED
	if _HEALTH_YELLOW in levels:
		return _HEALTH_YELLOW
	return _HEALTH_GREEN


def _fft_peak_frequency(spectrum: np.ndarray, f_axis: np.ndarray) -> float:
	"""Return FFT peak frequency (Hz) from spectrum argmax or 0.0 if invalid."""
	if spectrum is None or f_axis is None or len(spectrum) == 0 or len(f_axis) == 0:
		return 0.0
	idx = int(np.argmax(spectrum))
	if idx < 0 or idx >= len(f_axis):
		return 0.0
	return float(f_axis[idx])

def _fft_real_size() -> int:
	"""Return the real FFT size (N) implied by 513 bins: N = 2*(bins-1)."""
	return 2 * (frame_schema.FFT_SIZE - 1)

def _fft_frequency_axis() -> np.ndarray:
	"""Return 0..Nyquist FFT axis (len=FFT_SIZE) for 125e6 sample rate."""
	fft_real_size = _fft_real_size()
	return np.arange(frame_schema.FFT_SIZE, dtype=float) * 125e6 / fft_real_size


def _fft_data_ok(dataset) -> bool:
	"""Check FFT axis and spectrum values for obvious corruption."""
	if dataset is None:
		return False
	f_axis = dataset.f
	if f_axis is None or len(f_axis) != frame_schema.FFT_SIZE:
		return False
	if not np.all(np.isfinite(f_axis)):
		return False
	expected_f = _fft_frequency_axis()
	if np.any(f_axis < 0.0) or np.any(f_axis > expected_f[-1]):
		return False
	if not np.allclose(f_axis, expected_f):
		return False
	for spectrum in dataset.spectrum:
		if spectrum is None or len(spectrum) != frame_schema.FFT_SIZE:
			return False
		if not np.all(np.isfinite(spectrum)):
			return False
		if np.any(spectrum < 0.0) or np.any(spectrum > 1e6):
			return False
	return True


def compute_health_snapshot(dataset, is_phasemeter: bool) -> HealthSnapshot:
	"""
	Compute top-bar health indicators from the current dataset.

	Parameters
	----------
	dataset : DataPackage
		Current snapshot values and FFT data.
	is_phasemeter : bool
		True when connected to a phasemeter-only server.
	"""
	fft_status = _HEALTH_GREEN if _fft_data_ok(dataset) else _HEALTH_RED

	i_levels = []
	for val in dataset.i:
		if val < 0.0:
			i_levels.append(_HEALTH_RED)
		elif val <= 1e-3:
			i_levels.append(_HEALTH_YELLOW)
		else:
			i_levels.append(_HEALTH_GREEN)
	i_status = _combine_health(i_levels)

	q_levels = []
	for val in dataset.q:
		abs_val = abs(val)
		if abs_val > 1.0:
			q_levels.append(_HEALTH_RED)
		elif abs_val <= 1e-9:
			q_levels.append(_HEALTH_GREEN)
		elif abs_val < 1.0:
			q_levels.append(_HEALTH_YELLOW)
		else:
			q_levels.append(_HEALTH_YELLOW)
	q_status = _combine_health(q_levels)

	if is_phasemeter:
		readout_levels = []
		for ch in range(2):
			readout = float(dataset.pir[ch])
			peak = _fft_peak_frequency(dataset.spectrum[ch], dataset.f)
			if readout < 0.0:
				readout_levels.append(_HEALTH_RED)
			elif readout == 0.0:
				readout_levels.append(_HEALTH_YELLOW)
			elif peak > 0.0 and abs(readout - peak) <= 0.1 * peak:
				readout_levels.append(_HEALTH_GREEN)
			else:
				readout_levels.append(_HEALTH_YELLOW)
		freq_readout_status = _combine_health(readout_levels)
		freq_error_status = _HEALTH_GREEN
		ctrl_status = _HEALTH_GREEN
	else:
		freq_readout_status = _HEALTH_GREEN
		freqerr_levels = []
		for val in dataset.freqerr:
			abs_val = abs(val)
			if abs_val > 1.0:
				freqerr_levels.append(_HEALTH_RED)
			elif 0.0 < abs_val < 1e-6:
				freqerr_levels.append(_HEALTH_GREEN)
			elif 1e-6 < abs_val < 1.0:
				freqerr_levels.append(_HEALTH_YELLOW)
			else:
				freqerr_levels.append(_HEALTH_YELLOW)
		freq_error_status = _combine_health(freqerr_levels)

		ctrl_levels = []
		for ch in range(2):
			max_abs = max(abs(dataset.piezo[ch]), abs(dataset.temp[ch]))
			if max_abs > 1.0:
				ctrl_levels.append(_HEALTH_RED)
			elif 0.0 < max_abs < 0.5:
				ctrl_levels.append(_HEALTH_GREEN)
			elif 0.5 < max_abs < 1.0:
				ctrl_levels.append(_HEALTH_YELLOW)
			else:
				ctrl_levels.append(_HEALTH_YELLOW)
		ctrl_status = _combine_health(ctrl_levels)

	return HealthSnapshot(
		fft=fft_status,
		i_value=i_status,
		q_value=q_status,
		freq_readout=freq_readout_status,
		freq_error=freq_error_status,
		ctrl=ctrl_status,
	)
def effective_beatfreq(spectrum: np.ndarray, beatfreq_val: float, f_axis: np.ndarray,
                       freq_thresh: float = 1e3, spec_thresh: float = 1e-5,
                       max_discrepancy_hz: float = 2e6) -> tuple:
    """
    Return beatfreq from server if valid, else compute from spectrum argmax.

    When server sends beatfreq=0 but spectrum has a peak, use client-side fallback
    so peak markers and Reacquire work correctly after reconnect. When server
    sends a value that disagrees strongly with spectrum argmax (e.g. after
    desync), prefer the spectrum-based peak.

    Parameters
    ----------
    spectrum : np.ndarray
        FFT magnitude spectrum.
    beatfreq_val : float
        Server-reported peak frequency (Hz).
    f_axis : np.ndarray
        Frequency axis (Hz) for spectrum bins.
    freq_thresh : float, optional
        Min Hz to trust server value. Default 1e3.
    spec_thresh : float, optional
        Min spectrum max (Vpp) to compute fallback. Default 1e-5.
    max_discrepancy_hz : float, optional
        If server value and spectrum argmax differ by more than this (Hz),
        prefer spectrum argmax. Default 2e6.

    Returns
    -------
    tuple of (float, bool)
        (effective peak frequency in Hz, used_fallback).
        used_fallback is True when client-side argmax was used instead of server.
    """
    argmax_freq = 0.0
    if len(spectrum) > 0 and np.max(spectrum) >= spec_thresh:
        idx = int(np.argmax(spectrum))
        argmax_freq = float(f_axis[idx]) if idx < len(f_axis) else 0.0

    if beatfreq_val >= freq_thresh:
        if argmax_freq > 0 and abs(beatfreq_val - argmax_freq) > max_discrepancy_hz:
            return (argmax_freq, True)
        return (float(beatfreq_val), False)
    return (argmax_freq, True)


def compute_freq_plot_t(dataset, is_phasemeter: bool,
                        ref_freqs_hz: Optional[List[float]] = None) -> List[np.ndarray]:
	"""
	Compute the time-series data for the frequency plot.

	In phasemeter mode, plot PIR (Hz). In laser-lock mode, plot PIR minus
	reference frequency setpoints (Hz).
	"""
	if is_phasemeter:
		return dataset.pir_t

	ref0 = float(ref_freqs_hz[0]) if ref_freqs_hz and len(ref_freqs_hz) > 0 else 0.0
	ref1 = float(ref_freqs_hz[1]) if ref_freqs_hz and len(ref_freqs_hz) > 1 else 0.0
	return [
		dataset.pir_t[0] - ref0,
		dataset.pir_t[1] - ref1,
	]


def infer_phasemeter_from_snapshot(dataset, freq_tol_hz: float = 1e-6,
                                   ctrl_tol: float = 1e-6,
                                   min_pir_hz: float = 1.0) -> bool:
	"""
	Heuristic: detect phasemeter mode from the current snapshot.

	Phasemeter frames copy PIR into FREQ_ERR and zero piezo/temp controls.
	"""
	pir = dataset.pir
	freqerr = dataset.freqerr
	if pir is None or freqerr is None:
		return False
	freq_match = np.all(np.abs(freqerr - pir) <= freq_tol_hz)
	ctrl_zero = (
		np.all(np.abs(dataset.piezo) <= ctrl_tol)
		and np.all(np.abs(dataset.temp) <= ctrl_tol)
	)
	pir_nonzero = np.any(np.abs(pir) >= min_pir_hz)
	return bool(freq_match and ctrl_zero and pir_nonzero)


def build_plot_view_model(dataset, freq_plot_t: Optional[List[np.ndarray]] = None) -> PlotViewModel:
	"""
	Build a view model for plots from a DataPackage.

	Parameters
	----------
	dataset : DataPackage
		Current dataset (current snapshot and time series).

	Parameters
	----------
	freq_plot_t : list of numpy.ndarray, optional
		Override for the frequency plot data; defaults to dataset.freqerr_t.

	Returns
	-------
	PlotViewModel
		View model with references to dataset arrays (no copy).
	"""
	if freq_plot_t is None:
		freq_plot_t = dataset.freqerr_t
	return PlotViewModel(
		f=dataset.f,
		spectrum=dataset.spectrum,
		pir=dataset.pir,
		beatfreq=dataset.beatfreq,
		t=dataset.t,
		i_t=dataset.i_t,
		q_t=dataset.q_t,
		freqerr_t=dataset.freqerr_t,
		freq_plot_t=freq_plot_t,
		piezo_t=dataset.piezo_t,
		temp_t=dataset.temp_t,
	)


class DataPackage:
	def __init__(self):
		"""Initialize empty dataset and time-series arrays for two channels."""
		self.cnt = 0  # count
		self.spectrum = [np.zeros(frame_schema.FFT_SIZE) for i in range(2)] # specrtrums
		self.pir = np.zeros(2)  # pir frequencies
		self.q = np.zeros(2)    # Q values
		self.i = np.zeros(2)    # I values
		self.piezo = np.zeros(2) # Piezo control signals
		self.temp = np.zeros(2) # temperature control signals
		self.freqerr = np.zeros(2) # pir frequency errors
		self.beatfreq = np.zeros(2)  # beatnote frequencies

		# --- GUI-related --------------------------------------
		self.f = _fft_frequency_axis()  # Fourier frequencies: bin k at k*fs/N
		self.t = np.linspace(0,1, glp.TIME_PNTS) # time
		self.pir_t = [np.zeros(glp.TIME_PNTS) for i in range(2)]
		self.q_t = [np.zeros(glp.TIME_PNTS) for i in range(2)]
		self.i_t = [np.zeros(glp.TIME_PNTS) for i in range(2)]
		self.piezo_t = [np.zeros(glp.TIME_PNTS) for i in range(2)]
		self.temp_t = [np.zeros(glp.TIME_PNTS) for i in range(2)]
		self.freqerr_t = [np.zeros(glp.TIME_PNTS) for i in range(2)]
		self.beatfreq_t = [np.zeros(glp.TIME_PNTS) for i in range(2)]

	def clear(self) -> None:
		"""Reset all data to initial state (zeros), clearing plots."""
		self.cnt = 0
		for i in range(2):
			self.spectrum[i].fill(0)
		self.pir.fill(0)
		self.q.fill(0)
		self.i.fill(0)
		self.piezo.fill(0)
		self.temp.fill(0)
		self.freqerr.fill(0)
		self.beatfreq.fill(0)
		self.t = np.linspace(0, 1, glp.TIME_PNTS)
		for i in range(2):
			self.pir_t[i].fill(0)
			self.q_t[i].fill(0)
			self.i_t[i].fill(0)
			self.piezo_t[i].fill(0)
			self.temp_t[i].fill(0)
			self.freqerr_t[i].fill(0)
			self.beatfreq_t[i].fill(0)

	@staticmethod
	def parse_frame(raw_data: List[float]) -> Optional[Frame]:
		"""
		Parse raw frame data (list of doubles) into a Frame object.

		Single place where frame parsing logic lives. Returns None if
		raw_data is invalid (None or wrong length).

		Parameters
		----------
		raw_data : list of float or None
			Exactly FRAME_SIZE_DOUBLES doubles, or None.

		Returns
		-------
		Frame or None
			Parsed frame with calibrated spectrum and tail fields, or None.
		"""
		if raw_data is None or len(raw_data) != frame_schema.FRAME_SIZE_DOUBLES:
			return None
		
		# Parse FFT spectra (apply calibration factor)
		spectrum_0 = np.array([
			raw_data[frame_schema.FFT_RESULT_CHAN1_START + i] * glp.ABS_CAL_FACTOR
			for i in range(frame_schema.FFT_SIZE)
		])
		spectrum_1 = np.array([
			raw_data[frame_schema.FFT_RESULT_CHAN2_START + i] * glp.ABS_CAL_FACTOR
			for i in range(frame_schema.FFT_SIZE)
		])
		
		# Parse tail fields (must match `server/esw/memory_map.h::FRAME_CONTENT_ADDRESS_OFFSET`)
		return Frame(
			cnt=int(raw_data[frame_schema.FRAME_COUNTER]),
			spectrum=[spectrum_0, spectrum_1],
			pir=np.array([raw_data[frame_schema.PLL0PIR], raw_data[frame_schema.PLL1PIR]]),
			q=np.array([raw_data[frame_schema.PLL0Q], raw_data[frame_schema.PLL1Q]]),
			i=np.array([raw_data[frame_schema.PLL0I], raw_data[frame_schema.PLL1I]]),
			piezo=np.array([raw_data[frame_schema.PIEZO_ACT0], raw_data[frame_schema.PIEZO_ACT1]]),
			temp=np.array([raw_data[frame_schema.TEMP_ACT0], raw_data[frame_schema.TEMP_ACT1]]),
			freqerr=np.array([raw_data[frame_schema.FREQ_ERR0], raw_data[frame_schema.FREQ_ERR1]]),
			beatfreq=np.array([raw_data[frame_schema.MAX_ABS_FREQ0], raw_data[frame_schema.MAX_ABS_FREQ1]]),
		)

	def substitute_data(self, data: Union[List[float], Frame, None]):
		"""
		Update this DataPackage with new frame data.

		Accepts raw frame list (parsed via parse_frame), a Frame object,
		or None (no-op).

		Parameters
		----------
		data : list of float, Frame, or None
			Raw frame list, already-parsed Frame, or None.

		Returns
		-------
		None
		"""
		# Parse raw data if needed
		if isinstance(data, Frame):
			frame = data
		elif data is None:
			return
		else:
			frame = self.parse_frame(data)
			if frame is None:
				return
		
		# Update current snapshot
		self.cnt = frame.cnt
		self.spectrum[0][:] = frame.spectrum[0]
		self.spectrum[1][:] = frame.spectrum[1]
		self.pir[:] = frame.pir
		self.q[:] = frame.q
		self.i[:] = frame.i
		self.piezo[:] = frame.piezo
		self.temp[:] = frame.temp
		self.freqerr[:] = frame.freqerr
		self.beatfreq[:] = frame.beatfreq

	def update_t(self):
		"""
		Append current snapshot to time-series.
		"""
		self.t = update_data_t(self.t, self.t[-1] + 1)
		self.pir_t = update_data_t2(self.pir_t, self.pir)
		self.q_t = update_data_t2(self.q_t, self.q)
		self.i_t = update_data_t2(self.i_t, self.i)
		self.piezo_t = update_data_t2(self.piezo_t, self.piezo)
		self.temp_t = update_data_t2(self.temp_t, self.temp)
		self.freqerr_t = update_data_t2(self.freqerr_t, self.freqerr)
		self.beatfreq_t = update_data_t2(self.beatfreq_t, self.beatfreq)


