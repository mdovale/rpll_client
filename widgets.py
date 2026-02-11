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
import time
import sys
import os
import json
import warnings
from pathlib import Path
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets
import datetime

import acquire as acq
import global_params as glp
import data_models as aux
import rp_protocol as rpc

class MyQSpinBox():
	def __init__(self, socket, label, valRange, step, num, factor=1.0):
		"""
		SpinBox that sends scaled integer value to RP on change.

		Parameters
		----------
		socket : socket.socket or None
			TCP socket to RedPitaya.
		label : str
			Label text for the control.
		valRange : tuple of (int, int)
			(min, max) for the spinbox.
		step : int or float
			Single step size.
		num : str
			Register ID as hex string (e.g. '03').
		factor : float, optional
			Scale factor: value_sent = int(factor * display_value). Default 1.0.
		"""
		self.socket = socket
		self.box = QtWidgets.QSpinBox()
		self.label = QtWidgets.QLabel(label)
		self.box.setRange(valRange[0],valRange[1])
		self.box.setSingleStep(int(step))
		self.num = num
		self.factor = factor

		self.box.valueChanged.connect(self.function)

	def set_socket(self, socket):
		"""
		Update the socket used for sending (e.g. on reconnect).

		Parameters
		----------
		socket : socket.socket or None
			TCP socket to RedPitaya. None disables sending.

		Returns
		-------
		None
		"""
		self.socket = socket

	def function(self):
		"""
		On value change: encode scaled value and send register write to RP.

		Reads spinbox value, applies factor, and sends via rp_protocol.
		No parameters. No return value.
		"""
		value = rpc.scaled_value_to_int(float(self.box.cleanText()), self.factor)
		rpc.send_register_write(self.socket, self.num, value)


class MyPgSpinBox(): # for offsets
	def __init__(self, socket, label, valRange, step, num):
		"""
		SpinBox for offset values; sends 14-bit signed encoding to RP on change.

		Parameters
		----------
		socket : socket.socket or None
			TCP socket to RedPitaya.
		label : str
			Label text.
		valRange : tuple of (float, float)
			(min, max) for the spinbox (e.g. [-0.99, 0.99]).
		step : float
			Single step size.
		num : str
			Register ID as hex string.
		"""
		self.socket = socket
		self.box = pg.SpinBox()
		self.label = QtWidgets.QLabel(label)
		self.box.setRange(valRange[0],valRange[1])
		self.box.setSingleStep(int(step))
		self.num = num

		self.box.valueChanged.connect(self.function)

	def set_socket(self, socket):
		"""
		Update the socket used for sending (e.g. on reconnect).

		Parameters
		----------
		socket : socket.socket or None
			TCP socket to RedPitaya. None disables sending.

		Returns
		-------
		None
		"""
		self.socket = socket

	def function(self):
		"""
		On value change: encode offset and send register write to RP.

		Reads spinbox value, encodes as 14-bit signed, sends via rp_protocol.
		No parameters. No return value.
		"""
		value = rpc.offset_float_to_int(self.box.value())
		rpc.send_register_write(self.socket, self.num, value)

class MyQPushButton(QtWidgets.QPushButton):
	def __init__(self, text, function, StyleSheet=None):
		"""
		PushButton with optional style; clicked connects to function.

		Parameters
		----------
		text : str
			Button label.
		function : callable
			Callback when clicked (no arguments).
		StyleSheet : str or None, optional
			Qt style sheet. Default is None.
		"""
		super().__init__()
		self.setText(text)
		if StyleSheet is not None:
			self.setStyleSheet(StyleSheet)
		self.clicked.connect(function)




class WidgetList():
	_CFG_DEFAULTS = {
		"ifreq_0": 10009765,
		"ifreq_1": 10009765,
		"gain_pll_p_0": 12,
		"gain_pll_p_1": 12,
		"gain_pll_i_0": 3,
		"gain_pll_i_1": 3,
		"freq_ref_loop_0": 0,
		"piezo_switch_loop_0": 0,
		"temp_switch_loop_0": 0,
		"piezo_sign_loop_0": 0,
		"temp_sign_loop_0": 0,
		"piezo_offset_0": 0.0,
		"temp_offset_0": 0.0,
		"piezo_gain_I_0": 0,
		"piezo_gain_II_0": 0,
		"temp_gain_P_0": 0,
		"temp_gain_I_0": 0,
		"freq_ref_loop_1": 0,
		"piezo_switch_loop_1": 0,
		"temp_switch_loop_1": 0,
		"piezo_sign_loop_1": 0,
		"temp_sign_loop_1": 0,
		"piezo_offset_1": 0.0,
		"temp_offset_1": 0.0,
		"piezo_gain_I_1": 0,
		"piezo_gain_II_1": 0,
		"temp_gain_P_1": 0,
		"temp_gain_I_1": 0,
		"freq_noise_floor_0": 0,
		"freq_noise_floor_1": 0,
		"freq_noise_corner_0": 1,
		"freq_noise_corner_1": 1,
	}

	def __init__(self, socket):
		"""
		Create all control widgets (phasemeter, servos, data logger) and load cfg.

		Parameters
		----------
		socket : socket.socket or None
			TCP socket to RedPitaya; can be set later via set_socket.
		"""
		self.socket = socket
		self.auto_pll_open_flag_0=0
		self.auto_pll_open_flag_1=0
		self.data_write_flag=0 
		self.beatfreq=np.zeros(2)
		self._data_output_path = ""  # path to current data dump file (data logger state)
		self._data_write_channels = (0, 1)
		self._data_stop_at_monotonic = None  # None => indefinite recording

		# === Declaration =================================================
		# --- DPLL ------------------------------------------------
		self.ifreq_0 = MyQSpinBox(self.socket, 'PLL initial frequency (Hz)', [0,62500000], 30517.578125, "03", factor=0.000032768)
		self.ifreq_1 = MyQSpinBox(self.socket, 'PLL initial frequency (Hz)', [0,62500000], 30517.578125, "04", factor=0.000032768)
		self.gain_pll_p_0 = MyQSpinBox(self.socket, 'PLL proportional gain (P)', [0,50], 1, "05")
		self.gain_pll_p_1 = MyQSpinBox(self.socket, 'PLL proportional gain (P)', [0,50], 1, "06")
		self.gain_pll_i_0 = MyQSpinBox(self.socket, 'PLL integrator gain (I)', [0,50], 1, "07")
		self.gain_pll_i_1 = MyQSpinBox(self.socket, 'PLL integrator gain (I)', [0,50], 1, "08")
		# --- PLL1: laser lock ------------------------------------------------
		self.freq_ref_loop_0 = MyQSpinBox(self.socket, 'Reference frequency (Hz)', [0,62500000], glp.FREQ_REF_STEP_0, "09", factor=0.268435456)
		self.piezo_switch_loop_0 = MyQSpinBox(self.socket, 'Switch', [0,1], 1, "0A")
		self.temp_switch_loop_0 = MyQSpinBox(self.socket, 'Switch', [0,1], 1, "0B")
		self.piezo_sign_loop_0 = MyQSpinBox(self.socket, 'Sign', [0,1], 1, "0C")
		self.temp_sign_loop_0 = MyQSpinBox(self.socket, 'Sign', [0,1], 1, "0D")
		self.piezo_offset_0 = MyPgSpinBox(self.socket, 'Offset', [-0.99,0.99], 0.01, "0E")
		self.temp_offset_0 = MyPgSpinBox(self.socket, 'Offset', [-0.99,0.99], 0.01, "0F")
		self.piezo_gain_I_0 = MyQSpinBox(self.socket, 'Gain I', [0,100], 1, "10")
		self.piezo_gain_II_0 = MyQSpinBox(self.socket, 'Gain double-I', [0,100], 1, "11")
		self.temp_gain_P_0 = MyQSpinBox(self.socket, 'Gain P', [0,100], 1, "12")
		self.temp_gain_I_0 = MyQSpinBox(self.socket, 'Gain I', [0,100], 1, "13")
		# --- PLL2: laser lock ------------------------------------------------
		self.freq_ref_loop_1 = MyQSpinBox(self.socket, 'Reference frequency (Hz)', [0,62500000], glp.FREQ_REF_STEP_1, "14", factor=0.268435456)
		self.piezo_switch_loop_1 = MyQSpinBox(self.socket, 'Switch', [0,1], 1, "15")
		self.temp_switch_loop_1 = MyQSpinBox(self.socket, 'Switch', [0,1], 1, "16")
		self.piezo_sign_loop_1 = MyQSpinBox(self.socket, 'Sign', [0,1], 1, "17")
		self.temp_sign_loop_1 = MyQSpinBox(self.socket, 'Sign', [0,1], 1, "18")
		self.piezo_offset_1 = MyPgSpinBox(self.socket, 'Offset', [-0.99,0.99], 0.01, "19")
		self.temp_offset_1 = MyPgSpinBox(self.socket, 'Offset', [-0.99,0.99], 0.01, "1A")
		self.piezo_gain_I_1 = MyQSpinBox(self.socket, 'Gain I', [0,100], 1, "1B")
		self.piezo_gain_II_1 = MyQSpinBox(self.socket, 'Gain double-I', [0,100], 1, "1C")
		self.temp_gain_P_1 = MyQSpinBox(self.socket, 'Gain P', [0,100], 1, "1D")
		self.temp_gain_I_1 = MyQSpinBox(self.socket, 'Gain I', [0,100], 1, "1E")
		# --- Laser frequency nosie: white noise floor ------------------------------------
		self.freq_noise_floor_0 = MyQSpinBox(self.socket, 'Noise floor (mHz)', [0,100000], 1000, "1F", factor=1e-3)
		self.freq_noise_floor_1 = MyQSpinBox(self.socket, 'Noise floor (mHz)', [0,100000], 1000, "20", factor=1e-3)
		self.freq_noise_corner_0 = MyQSpinBox(self.socket, 'Corner freq. (Hz)', [1,100000], 10, "21") # to change the minimum, you need to also change server.c
		self.freq_noise_corner_1 = MyQSpinBox(self.socket, 'Corner freq. (Hz)', [1,100000], 10, "22") # to change the minimum, you need to also change server.c

		# Keep a list of controls that need their socket updated on reconnect.
		self._socket_controls = [
			self.ifreq_0, self.ifreq_1,
			self.gain_pll_p_0, self.gain_pll_p_1,
			self.gain_pll_i_0, self.gain_pll_i_1,
			self.freq_ref_loop_0, self.freq_ref_loop_1,
			self.piezo_switch_loop_0, self.piezo_switch_loop_1,
			self.temp_switch_loop_0, self.temp_switch_loop_1,
			self.piezo_sign_loop_0, self.piezo_sign_loop_1,
			self.temp_sign_loop_0, self.temp_sign_loop_1,
			self.piezo_offset_0, self.piezo_offset_1,
			self.temp_offset_0, self.temp_offset_1,
			self.piezo_gain_I_0, self.piezo_gain_I_1,
			self.piezo_gain_II_0, self.piezo_gain_II_1,
			self.temp_gain_P_0, self.temp_gain_P_1,
			self.temp_gain_I_0, self.temp_gain_I_1,
			self.freq_noise_floor_0, self.freq_noise_floor_1,
			self.freq_noise_corner_0, self.freq_noise_corner_1,
		]
		# --- Reset ---------------------------------------------
		# *** open the loop ************************************
		self.pushButton_open_pll_0 = MyQPushButton("PLL1: Auto Disengage (OFF)",self.auto_pll_open_0, "*{background-color:red; color:black; border-style:inset;}")
		self.pushButton_open_pll_1 = MyQPushButton("PLL2: Auto Disengage (OFF)",self.auto_pll_open_1, "*{background-color:red; color:black; border-style:inset;}")
		self.pushButton_open_pll_0.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
		self.pushButton_open_pll_1.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
		self.pushButton_open_pll_0.setMinimumHeight(32)
		self.pushButton_open_pll_1.setMinimumHeight(32)
		# *** Reset registers ***********************************
		self.pushButton_reset_a = QtWidgets.QPushButton()
		self.pushButton_reset_a.setText("Reacquire")

		# --- phasemeter settings helpers ------------------------------
		self.pushButton_copy_settings_ch2 = QtWidgets.QPushButton()
		self.pushButton_copy_settings_ch2.setText("Copy settings to channel 2")
		self.pushButton_copy_settings_ch2.clicked.connect(self.copy_settings_to_channel_2)

		# --- beatnote frequencies ---------------------------------------------
		self.pushButton_peakfreq_0 = MyQPushButton("Peak Frequency",self.use_peakfreq0)
		self.pushButton_peakfreq_1 = MyQPushButton("Peak Frequency",self.use_peakfreq0)

		# --- data dumping ---------------------------------------------
		self.pushButton_datwrite_0 = QtWidgets.QPushButton()
		self.pushButton_datwrite_0.setText("Start Logging")
		self.pushButton_datwrite_0.clicked.connect(self.datdumpflag)

		self.checkBox_log_ch1 = QtWidgets.QCheckBox("Ch1")
		self.checkBox_log_ch2 = QtWidgets.QCheckBox("Ch2")
		self.checkBox_log_ch1.setChecked(True)
		self.checkBox_log_ch2.setChecked(True)
		self.checkBox_log_ch1.toggled.connect(self._update_data_logger_ui_enabled)
		self.checkBox_log_ch2.toggled.connect(self._update_data_logger_ui_enabled)

		self.logging_status_dot = QtWidgets.QLabel()
		self.logging_status_dot.setFixedSize(12, 12)
		self._set_logging_indicator(False)

		self.data_logger_controls_widget = QtWidgets.QWidget()
		_data_logger_controls_layout = QtWidgets.QHBoxLayout()
		_data_logger_controls_layout.setContentsMargins(0, 0, 0, 0)
		_data_logger_controls_layout.setSpacing(8)
		_data_logger_controls_layout.addWidget(self.pushButton_datwrite_0)
		_data_logger_controls_layout.addWidget(self.checkBox_log_ch1)
		_data_logger_controls_layout.addWidget(self.checkBox_log_ch2)
		_data_logger_controls_layout.addWidget(self.logging_status_dot)
		_data_logger_controls_layout.addStretch(1)
		self.data_logger_controls_widget.setLayout(_data_logger_controls_layout)

		self.label_record_length = QtWidgets.QLabel("Record length:")
		self.spinBox_record_hours = QtWidgets.QSpinBox()
		self.spinBox_record_minutes = QtWidgets.QSpinBox()
		self.spinBox_record_seconds = QtWidgets.QSpinBox()

		for _box in (self.spinBox_record_hours, self.spinBox_record_minutes, self.spinBox_record_seconds):
			_box.setSingleStep(1)
			_box.setFixedWidth(70)

		self.data_logger_record_length_fields_widget = QtWidgets.QWidget()
		_record_fields_layout = QtWidgets.QHBoxLayout()
		_record_fields_layout.setContentsMargins(0, 0, 0, 0)
		_record_fields_layout.setSpacing(6)
		_record_fields_layout.addWidget(self.label_record_length)
		_record_fields_layout.addWidget(QtWidgets.QLabel("Hours :"))
		_record_fields_layout.addWidget(self.spinBox_record_hours)
		_record_fields_layout.addWidget(QtWidgets.QLabel("Minutes :"))
		_record_fields_layout.addWidget(self.spinBox_record_minutes)
		_record_fields_layout.addWidget(QtWidgets.QLabel("Seconds :"))
		_record_fields_layout.addWidget(self.spinBox_record_seconds)
		_record_fields_layout.addStretch(1)
		self.data_logger_record_length_fields_widget.setLayout(_record_fields_layout)

		self.label_record_length_note = QtWidgets.QLabel("Enter 0 : 0 : 0 for indefinite length")
		self.label_record_length_note.setStyleSheet("color: #666;")

		# === setup ======================================================
		self.setRange()
		self.setInitialValues(os.path.join(os.path.dirname(__file__), 'config.json'))
		self.connectFunctions()
		self._update_data_logger_ui_enabled()

	def _selected_data_logger_channels_from_ui(self):
		"""Return selected channels (0/1) from Data Logger checkboxes."""
		channels = []
		if getattr(self, "checkBox_log_ch1", None) is not None and self.checkBox_log_ch1.isChecked():
			channels.append(0)
		if getattr(self, "checkBox_log_ch2", None) is not None and self.checkBox_log_ch2.isChecked():
			channels.append(1)
		return tuple(channels)

	def _update_data_logger_ui_enabled(self):
		"""
		Enable/disable Start Logging when no channels selected.

		When logging is active, the button stays enabled (to allow Stop Logging)
		and channel checkboxes are disabled to avoid changing the file format mid-run.
		"""
		is_logging = bool(self.data_write_flag == 1)
		channels = self._selected_data_logger_channels_from_ui()
		can_start = bool(channels)
		if hasattr(self, "pushButton_datwrite_0") and self.pushButton_datwrite_0 is not None:
			self.pushButton_datwrite_0.setEnabled(is_logging or can_start)
		for cb in (getattr(self, "checkBox_log_ch1", None), getattr(self, "checkBox_log_ch2", None)):
			if cb is not None:
				cb.setEnabled(not is_logging)

	def set_socket(self, socket):
		"""
		Update socket for all controls that send to RP.

		When socket becomes non-None (connection established), push all current
		widget values to the server so it receives config.json settings (initial
		frequency, gains, etc.). Without this, the server defaults to 0 and
		the PLL integrators push the PIR away from the signal.

		Parameters
		----------
		socket : socket.socket or None
			TCP socket to RedPitaya. Propagated to all MyQSpinBox/MyPgSpinBox.

		Returns
		-------
		None
		"""
		self.socket = socket
		for ctrl in getattr(self, "_socket_controls", []):
			ctrl.set_socket(socket)
		if socket is not None:
			for ctrl in getattr(self, "_socket_controls", []):
				if hasattr(ctrl, "function"):
					ctrl.function()


	def setRange(self):
		"""
		Set ranges for record length entry fields.

		No parameters. Modifies record length spinboxes in place.

		Returns
		-------
		None
		"""
		max_hours = 24 * 365 * 30  # ~30 years
		self.spinBox_record_hours.setRange(0, max_hours)
		self.spinBox_record_minutes.setRange(0, 59)
		self.spinBox_record_seconds.setRange(0, 59)

	def _format_int_box(self, box):
		return int(box.value())

	def _format_float_box(self, box):
		return float(box.value())

	def _cfg_entries(self):
		int_formatter = self._format_int_box
		float_formatter = self._format_float_box
		return [
			("ifreq_0", self.ifreq_0.box, int, int_formatter, self._CFG_DEFAULTS["ifreq_0"]),
			("ifreq_1", self.ifreq_1.box, int, int_formatter, self._CFG_DEFAULTS["ifreq_1"]),
			("gain_pll_p_0", self.gain_pll_p_0.box, int, int_formatter, self._CFG_DEFAULTS["gain_pll_p_0"]),
			("gain_pll_p_1", self.gain_pll_p_1.box, int, int_formatter, self._CFG_DEFAULTS["gain_pll_p_1"]),
			("gain_pll_i_0", self.gain_pll_i_0.box, int, int_formatter, self._CFG_DEFAULTS["gain_pll_i_0"]),
			("gain_pll_i_1", self.gain_pll_i_1.box, int, int_formatter, self._CFG_DEFAULTS["gain_pll_i_1"]),
			("freq_ref_loop_0", self.freq_ref_loop_0.box, int, int_formatter, self._CFG_DEFAULTS["freq_ref_loop_0"]),
			("piezo_switch_loop_0", self.piezo_switch_loop_0.box, int, int_formatter, self._CFG_DEFAULTS["piezo_switch_loop_0"]),
			("temp_switch_loop_0", self.temp_switch_loop_0.box, int, int_formatter, self._CFG_DEFAULTS["temp_switch_loop_0"]),
			("piezo_sign_loop_0", self.piezo_sign_loop_0.box, int, int_formatter, self._CFG_DEFAULTS["piezo_sign_loop_0"]),
			("temp_sign_loop_0", self.temp_sign_loop_0.box, int, int_formatter, self._CFG_DEFAULTS["temp_sign_loop_0"]),
			("piezo_offset_0", self.piezo_offset_0.box, float, float_formatter, self._CFG_DEFAULTS["piezo_offset_0"]),
			("temp_offset_0", self.temp_offset_0.box, float, float_formatter, self._CFG_DEFAULTS["temp_offset_0"]),
			("piezo_gain_I_0", self.piezo_gain_I_0.box, int, int_formatter, self._CFG_DEFAULTS["piezo_gain_I_0"]),
			("piezo_gain_II_0", self.piezo_gain_II_0.box, int, int_formatter, self._CFG_DEFAULTS["piezo_gain_II_0"]),
			("temp_gain_P_0", self.temp_gain_P_0.box, int, int_formatter, self._CFG_DEFAULTS["temp_gain_P_0"]),
			("temp_gain_I_0", self.temp_gain_I_0.box, int, int_formatter, self._CFG_DEFAULTS["temp_gain_I_0"]),
			("freq_ref_loop_1", self.freq_ref_loop_1.box, int, int_formatter, self._CFG_DEFAULTS["freq_ref_loop_1"]),
			("piezo_switch_loop_1", self.piezo_switch_loop_1.box, int, int_formatter, self._CFG_DEFAULTS["piezo_switch_loop_1"]),
			("temp_switch_loop_1", self.temp_switch_loop_1.box, int, int_formatter, self._CFG_DEFAULTS["temp_switch_loop_1"]),
			("piezo_sign_loop_1", self.piezo_sign_loop_1.box, int, int_formatter, self._CFG_DEFAULTS["piezo_sign_loop_1"]),
			("temp_sign_loop_1", self.temp_sign_loop_1.box, int, int_formatter, self._CFG_DEFAULTS["temp_sign_loop_1"]),
			("piezo_offset_1", self.piezo_offset_1.box, float, float_formatter, self._CFG_DEFAULTS["piezo_offset_1"]),
			("temp_offset_1", self.temp_offset_1.box, float, float_formatter, self._CFG_DEFAULTS["temp_offset_1"]),
			("piezo_gain_I_1", self.piezo_gain_I_1.box, int, int_formatter, self._CFG_DEFAULTS["piezo_gain_I_1"]),
			("piezo_gain_II_1", self.piezo_gain_II_1.box, int, int_formatter, self._CFG_DEFAULTS["piezo_gain_II_1"]),
			("temp_gain_P_1", self.temp_gain_P_1.box, int, int_formatter, self._CFG_DEFAULTS["temp_gain_P_1"]),
			("temp_gain_I_1", self.temp_gain_I_1.box, int, int_formatter, self._CFG_DEFAULTS["temp_gain_I_1"]),
			("freq_noise_floor_0", self.freq_noise_floor_0.box, int, int_formatter, self._CFG_DEFAULTS["freq_noise_floor_0"]),
			("freq_noise_floor_1", self.freq_noise_floor_1.box, int, int_formatter, self._CFG_DEFAULTS["freq_noise_floor_1"]),
			("freq_noise_corner_0", self.freq_noise_corner_0.box, int, int_formatter, self._CFG_DEFAULTS["freq_noise_corner_0"]),
			("freq_noise_corner_1", self.freq_noise_corner_1.box, int, int_formatter, self._CFG_DEFAULTS["freq_noise_corner_1"]),
		]

	def _apply_cfg_values(self, entries, values):
		for key, box, _parser, _formatter, _default in entries:
			box.setValue(values[key])

	def _write_cfg(self, filen, entries):
		path = Path(filen)
		path.parent.mkdir(parents=True, exist_ok=True)
		payload = {key: formatter(box) for key, box, _parser, formatter, _default in entries}
		path.write_text(json.dumps(payload, indent=2) + "\n")

	def _reset_cfg_to_defaults(self, filen, reason, entries):
		warnings.warn(
			f"Config file {filen} {reason}; recreating with defaults.",
			RuntimeWarning,
		)
		defaults = {key: default for key, _box, _parser, _formatter, default in entries}
		self._apply_cfg_values(entries, defaults)
		self._write_cfg(filen, entries)

	def _legacy_cfg_path(self, filen):
		return Path(filen).with_name("cfg.txt")

	def _parse_cfg_payload(self, payload, entries):
		if not isinstance(payload, dict):
			raise TypeError("config payload is not a JSON object")
		values = {}
		for key, _box, parser, _formatter, _default in entries:
			if key not in payload:
				raise KeyError(f"missing key {key}")
			values[key] = parser(payload[key])
		return values

	def _parse_legacy_cfg(self, lines, entries):
		if len(lines) != len(entries):
			raise ValueError(f"expected {len(entries)} lines, got {len(lines)}")
		values = {}
		for (key, _box, parser, _formatter, _default), line in zip(entries, lines):
			values[key] = parser(line.strip())
		return values

	def setInitialValues(self, filen):
		"""
		Load widget values from a JSON config file.

		Parameters
		----------
		filen : str
			Path to config file (e.g. config.json).
		"""
		entries = self._cfg_entries()
		path = Path(filen)
		legacy_path = self._legacy_cfg_path(filen)
		try:
			payload = json.loads(path.read_text())
			values = self._parse_cfg_payload(payload, entries)
		except FileNotFoundError:
			if legacy_path.exists():
				try:
					lines = legacy_path.read_text().splitlines()
					values = self._parse_legacy_cfg(lines, entries)
				except (OSError, ValueError, TypeError) as exc:
					self._reset_cfg_to_defaults(
						filen,
						f"is missing and legacy cfg.txt is invalid ({exc})",
						entries,
					)
					return
				warnings.warn(
					f"Config file {filen} is missing; migrated values from cfg.txt.",
					RuntimeWarning,
				)
				self._apply_cfg_values(entries, values)
				self._write_cfg(filen, entries)
				return
			self._reset_cfg_to_defaults(filen, "is missing", entries)
			return
		except (json.JSONDecodeError, OSError, TypeError, KeyError, ValueError) as exc:
			self._reset_cfg_to_defaults(
				filen,
				f"contains invalid JSON ({exc})",
				entries,
			)
			return
		self._apply_cfg_values(entries, values)

	def setFinalValues(self, filen):
		"""
		Save current widget values to a JSON config file.

		Parameters
		----------
		filen : str
			Path to config file (e.g. config.json).
		"""
		entries = self._cfg_entries()
		self._write_cfg(filen, entries)

	def connectFunctions(self):
		"""
		Connect spinboxes and reset buttons to their callbacks.

		Wires reset_a to its handlers. No parameters.

		Returns
		-------
		None
		"""
		self.pushButton_reset_a.pressed.connect(self.send_activate_reset_pll_dsp)       
		self.pushButton_reset_a.released.connect(self.send_release_reset_pll_dsp)

	def copy_settings_to_channel_2(self):
		"""
		Copy channel 1 phasemeter settings (ifreq, gain P/I) to channel 2.

		Sends to RP via valueChanged when spinbox values are set. No parameters.

		Returns
		-------
		None
		"""
		self.ifreq_1.box.setValue(self.ifreq_0.box.value())
		self.gain_pll_p_1.box.setValue(self.gain_pll_p_0.box.value())
		self.gain_pll_i_1.box.setValue(self.gain_pll_i_0.box.value())


	def send_activate_reset_pll_dsp(self):
		"""
		Send reset hold to RP and set both channels' initial freq to current peak.

		Calls send_reset(release=False) then use_peakfreq0/use_peakfreq1. No parameters.

		Returns
		-------
		None
		"""
		rpc.send_reset(self.socket, release=False)
		self.use_peakfreq0()
		self.use_peakfreq1()

	def send_release_reset_pll_dsp(self):
		"""
		Send reset release to RP.

		Calls send_reset(release=True). Does not call use_peakfreq, because
		_on_reacquire (on press) clears beatfreq to zero; calling use_peakfreq
		on release would overwrite Initial frequency with 0.

		Returns
		-------
		None
		"""
		rpc.send_reset(self.socket, release=True)

	def auto_pll_open_0(self):
		"""
		Toggle PLL1 Auto Disengage: when on, turns off piezo/temp if freq error large.

		Flips auto_pll_open_flag_0 and updates button text/style. No parameters.

		Returns
		-------
		None
		"""
		if self.auto_pll_open_flag_0==0: 
			self.pushButton_open_pll_0.setText("PLL1: Auto Disengage (ON)")
			self.pushButton_open_pll_0.setStyleSheet( "*{background-color:green; color:white; border-style:inset;}")
			self.auto_pll_open_flag_0=1

		elif self.auto_pll_open_flag_0==1: 
			self.pushButton_open_pll_0.setText("PLL1: Auto Disengage (OFF)")
			self.pushButton_open_pll_0.setStyleSheet( "*{background-color:red; color:black; border-style:inset;}")
			self.auto_pll_open_flag_0=0

	def auto_pll_open_1(self):
		"""
		Toggle PLL2 Auto Disengage: when on, turns off piezo/temp if freq error large.

		Flips auto_pll_open_flag_1 and updates button text/style. No parameters.

		Returns
		-------
		None
		"""
		if self.auto_pll_open_flag_1==0:
			self.pushButton_open_pll_1.setText("PLL2: Auto Disengage (ON)")
			self.pushButton_open_pll_1.setStyleSheet( "*{background-color:green; color:white; border-style:inset;}")
			self.auto_pll_open_flag_1=1

		elif self.auto_pll_open_flag_1==1: 
			self.pushButton_open_pll_1.setText("PLL2: Auto Disengage (OFF)")
			self.pushButton_open_pll_1.setStyleSheet( "*{background-color:red; color:black; border-style:inset;}")
			self.auto_pll_open_flag_1=0


	def processing(self, dataset):
		"""
		Per-tick processing: data dump, auto PLL turn-off.

		Parameters
		----------
		dataset : DataPackage
			Current dataset (for beatfreq, etc.).

		Returns
		-------
		None
		"""
		if self.data_write_flag==1:
			self.datwrite(dataset) #write the data into file
		if self.auto_pll_open_flag_0==1:
			self.turn_off_pll_0(dataset)
		if self.auto_pll_open_flag_1==1:
			self.turn_off_pll_1(dataset)


	def turn_off_pll_0(self, dataset):
		"""
		If beatfreq deviates from ref by > LOCK_THRESHOLD_FREQ, turn off piezo/temp for channel 0.

		Parameters
		----------
		dataset : DataPackage
			Current dataset (uses beatfreq[0]).

		Returns
		-------
		None
		"""
		diff_f = abs(dataset.beatfreq[0] - self.freq_ref_loop_0.box.value()) # difference between the reference and actual frequency
		if diff_f > glp.LOCK_THRESHOLD_FREQ:
			self.piezo_switch_loop_0.box.setValue(0)
			self.temp_switch_loop_0.box.setValue(0) 
	    

	def turn_off_pll_1(self, dataset):
		"""
		If beatfreq deviates from ref by > LOCK_THRESHOLD_FREQ, turn off piezo/temp for channel 1.

		Parameters
		----------
		dataset : DataPackage
			Current dataset (uses beatfreq[1]).

		Returns
		-------
		None
		"""
		diff_f = abs(dataset.beatfreq[1] - self.freq_ref_loop_1.box.value()) # difference between the reference and actual frequency
		if diff_f > glp.LOCK_THRESHOLD_FREQ:
			self.piezo_switch_loop_1.box.setValue(0)
			self.temp_switch_loop_1.box.setValue(0) 


	def use_peakfreq0(self):
		"""
		Set channel 0 initial frequency to current beat frequency (sends to RP).

		Sets ifreq_0 spinbox to beatfreq[0]; valueChanged sends to RP. No parameters.

		Returns
		-------
		None
		"""
		self.ifreq_0.box.setValue(int(self.beatfreq[0]))

	def use_peakfreq1(self):
		"""
		Set channel 1 initial frequency to current beat frequency (sends to RP).

		Sets ifreq_1 spinbox to beatfreq[1]; valueChanged sends to RP. No parameters.

		Returns
		-------
		None
		"""
		self.ifreq_1.box.setValue(int(self.beatfreq[1]))

	def _set_logging_indicator(self, is_logging: bool) -> None:
		"""Update the red/green circular status indicator."""
		color = "green" if is_logging else "red"
		self.logging_status_dot.setStyleSheet(
			f"background-color:{color}; border-radius:6px; border:1px solid #333;"
		)

	def _record_length_seconds_from_ui(self):
		"""
		Return record length in seconds from Hours/Minutes/Seconds fields.

		A value of 0 means indefinite.
		"""
		h = int(self.spinBox_record_hours.value())
		m = int(self.spinBox_record_minutes.value())
		s = int(self.spinBox_record_seconds.value())
		return max(0, h * 3600 + m * 60 + s)

	def _set_record_length_fields_from_seconds(self, duration_s: int) -> None:
		duration_s = max(0, int(duration_s))
		h = duration_s // 3600
		rem = duration_s % 3600
		m = rem // 60
		s = rem % 60
		self.spinBox_record_hours.setValue(int(h))
		self.spinBox_record_minutes.setValue(int(m))
		self.spinBox_record_seconds.setValue(int(s))

	def datadump_timer(self):
		"""
		Auto-stop logging when the configured record length elapses.

		Called periodically (e.g. every 1 s). No parameters.

		Returns
		-------
		None
		"""
		if self.data_write_flag != 1:
			return
		if self._data_stop_at_monotonic is None:
			return
		if time.monotonic() >= self._data_stop_at_monotonic:
			self.stop_datadump()

	def _normalize_data_channels(self, channels):
		"""Return a tuple of valid channel indices (0/1) from an iterable."""
		if channels is None:
			return self._data_write_channels or (0, 1)
		result = []
		for ch in channels:
			if ch in (0, 1) and ch not in result:
				result.append(ch)
		return tuple(result)

	def _data_dump_columns(self, dataset):
		"""Return ordered (label, value, channel) tuples for a data dump row."""
		return [
			("PIR_0", dataset.pir[0], 0),
			("PIR_1", dataset.pir[1], 1),
			("Q_0", dataset.q[0], 0),
			("Q_1", dataset.q[1], 1),
			("I_0", dataset.i[0], 0),
			("I-1", dataset.i[1], 1),
			("Piezo_0", dataset.piezo[0], 0),
			("Piezo_1", dataset.piezo[1], 1),
			("Temperature_0", dataset.temp[0], 0),
			("Temperature_1", dataset.temp[1], 1),
			("FreqErr_0", dataset.freqerr[0], 0),
			("FreqErr_1", dataset.freqerr[1], 1),
		]

	def _data_dump_labels(self):
		"""Return ordered (label, channel) tuples for a data dump header."""
		return [
			("PIR_0", 0),
			("PIR_1", 1),
			("Q_0", 0),
			("Q_1", 1),
			("I_0", 0),
			("I-1", 1),
			("Piezo_0", 0),
			("Piezo_1", 1),
			("Temperature_0", 0),
			("Temperature_1", 1),
			("FreqErr_0", 0),
			("FreqErr_1", 1),
		]

	def start_datadump(self, output_path=None, channels=None, duration_s=None):
		"""
		Start data dumping to output_path (or default) with channel selection.

		Parameters
		----------
		output_path : str or None
			File path to write. If None, use readout/<timestamp>/<timestamp>_data.txt.
		channels : iterable or None
			Channels to include (0 and/or 1).
		duration_s : int or None
			If provided (or if UI record length is non-zero), auto-stop after duration_s.
			A value of 0 means indefinite.
		"""
		if self.data_write_flag == 1:
			return False
		self._data_write_channels = self._normalize_data_channels(channels)
		if not self._data_write_channels:
			return False
		# Sync Data Logger UI (if present) to match selection.
		try:
			if getattr(self, "checkBox_log_ch1", None) is not None:
				self.checkBox_log_ch1.setChecked(0 in self._data_write_channels)
			if getattr(self, "checkBox_log_ch2", None) is not None:
				self.checkBox_log_ch2.setChecked(1 in self._data_write_channels)
		except Exception:
			pass
		if duration_s is None:
			duration_s = self._record_length_seconds_from_ui()
		else:
			duration_s = max(0, int(duration_s))
			self._set_record_length_fields_from_seconds(duration_s)
		self._data_stop_at_monotonic = None if duration_s == 0 else (time.monotonic() + duration_s)

		dat_time = datetime.datetime.now()
		dtheader = dat_time.strftime("%Y-%m-%d %H:%M:%S")
		filetime = dat_time.strftime("%Y_%m_%d_%H_%M_%S")
		if output_path:
			out_path = Path(output_path)
		else:
			repo_root = Path(__file__).resolve().parent.parent
			out_path = repo_root / "readout" / filetime / f"{filetime}_data.txt"
		out_path.parent.mkdir(parents=True, exist_ok=True)
		self._data_output_path = str(out_path)
		columns = ["cnts"]
		for label, channel in self._data_dump_labels():
			if channel in self._data_write_channels:
				columns.append(label)

		with open(self._data_output_path, 'w') as file:
			print("Start date: "+str(dtheader))
			file.write("#\n")
			file.write("# t0: "+str(dtheader)+"\n")
			file.write("# fs: "+str(glp.fs)+"[Hz]\n")
			file.write("#\n")
			file.write(" ".join(columns)+"\n")
		self.pushButton_datwrite_0.setText("Stop Logging")
		self._set_logging_indicator(True)
		self.data_write_flag=1
		self._update_data_logger_ui_enabled()
		return True

	def stop_datadump(self):
		"""Stop data dumping if active."""
		if self.data_write_flag == 0:
			return False
		dat_time = datetime.datetime.now()
		dtheader = dat_time.strftime("%Y-%m-%d %H:%M:%S")
		print("End date: "+str(dtheader))
		self.pushButton_datwrite_0.setText("Start Logging")
		self._set_logging_indicator(False)
		self.data_write_flag=0
		self._data_stop_at_monotonic = None
		self._update_data_logger_ui_enabled()
		return True

	def datdumpflag(self):
		"""
		Toggle data dumping: start (create file, set path) or stop.

		When turning on: creates readout/<timestamp>/<timestamp>_data.txt, sets
		_data_output_path, writes header. When turning off: updates button.
		No parameters.

		Returns
		-------
		None
		"""
		if self.data_write_flag==0:
			channels = self._selected_data_logger_channels_from_ui()
			if not channels:
				self._update_data_logger_ui_enabled()
				return
			self.start_datadump(channels=channels)
		elif self.data_write_flag==1:
			self.stop_datadump()


	def datwrite(self, dataset):
		"""
		Append one line of current snapshot to data file.

		Parameters
		----------
		dataset : DataPackage
			Current dataset (cnt, pir, q, i, piezo, temp, freqerr).

		Returns
		-------
		None
		"""
		if not self._data_output_path:
			return
		channels = self._data_write_channels or (0, 1)
		column_defs = self._data_dump_columns(dataset)
		values = [str(dataset.cnt)]
		for _label, value, channel in column_defs:
			if channel in channels:
				values.append(str(value))
		with open(self._data_output_path, 'a') as file:
			file.write(" ".join(values) + "\n")
		file.close
