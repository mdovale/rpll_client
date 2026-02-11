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
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui
from pyqtgraph import functions as fn
import struct
import datetime

import global_params as glp


class _AxisSeparateScrollViewBox(pg.ViewBox):
	"""ViewBox where vertical scroll changes only y-axis, horizontal scroll only x-axis."""

	def wheelEvent(self, ev, axis=None):
		# QGraphicsSceneWheelEvent has delta() and orientation(), not angleDelta()
		delta_val = ev.delta() if hasattr(ev, 'delta') else 0
		orient = ev.orientation() if hasattr(ev, 'orientation') else QtCore.Qt.Orientation.Vertical
		is_horizontal = orient == QtCore.Qt.Orientation.Horizontal

		mouse_enabled = self.state['mouseEnabled'][:]
		if is_horizontal:
			mask = [mouse_enabled[0], False]
		else:
			mask = [False, mouse_enabled[1]]

		if delta_val == 0:
			ev.ignore()
			return

		if not any(mask):
			ev.ignore()
			return

		delta = delta_val
		s = 1.02 ** (delta * self.state['wheelScaleFactor'])
		s = [(None if m is False else s) for m in mask]
		center = fn.invertQTransform(self.childGroup.transform()).map(ev.pos())
		center = pg.Point(center)

		self._resetTarget()
		self.scaleBy(s, center)
		ev.accept()
		self.sigRangeChangedManually.emit(mask)


class GuiLayout():
	def __init__(self):
		"""
		Create plot widgets for spectrum, I/Q, freq error, and ctrl signals.

		Spectrum Analyzer pan/zoom is clamped to [0, 125e6] Hz and y >= 100 uVpp.
		No parameters; initializes all plot widgets and curves.
		"""
		# === plots =================================================
		# Track plot widgets and per-plot state for menu actions.
		self._plot_widgets = {}
		self._plot_channel_items = {}
		self._plot_autoscale_y = {}
		self._active_plot_key = None
		# --- widget: spectrum -----------------------------
		# Spectrum Analyzer QoL: clamp pan/zoom to sane limits.
		# - x-axis: never < 0 Hz and never > 125e6 Hz
		# - y-axis: always starts at 0 and never zooms to < 100 uVpp range
		self._sa_x_min_hz = 0.0
		self._sa_x_max_hz = 125e6
		self._sa_y_min_hard_vpp = 0.0
		self._sa_y_min_range_vpp = 100e-6
		self._sa_is_clamping = False

		_vb = _AxisSeparateScrollViewBox()
		self.pltSA = pg.PlotWidget(viewBox=_vb)
		self.pltSA.setTitle("Spectrum")
		self.pltSA.setLabel('left',text="Beatnote Amplitude", units='Vpp')
		self.pltSA.setLabel('bottom',text="Fourier Frequency", units='Hz')
		self.pltSA.setRange(xRange = (0.0, glp.FourierMax))
		# Enforce hard limits for mouse pan/zoom.
		self._sa_vb = _vb
		self._sa_vb.setLimits(
			xMin=self._sa_x_min_hz,
			xMax=self._sa_x_max_hz,
			yMin=self._sa_y_min_hard_vpp,
			minYRange=self._sa_y_min_range_vpp,
		)
		# Also pin y_min to 0 (prevents zooming/panning to y_min > 0).
		self._sa_vb.sigRangeChanged.connect(self._on_sa_range_changed)
		self.curveSA1=self.pltSA.plot(pen='g')
		self.curveSA2=self.pltSA.plot(pen='c')
		# PIR vertical lines: channel 0 green, channel 1 cyan (match curve colors)
		self.pirSA1=self.pltSA.plot(pen='g')
		self.pirSA2=self.pltSA.plot(pen='c')
		# FFT peak markers: ScatterPlotItem for reliable single-point display
		self.peakSA1 = pg.ScatterPlotItem(symbol='+', size=14, pen=pg.mkPen('g'), brush=pg.mkBrush('g'))
		self.peakSA2 = pg.ScatterPlotItem(symbol='x', size=14, pen=pg.mkPen('c'), brush=pg.mkBrush('c'))
		self.pltSA.addItem(self.peakSA1)
		self.pltSA.addItem(self.peakSA2)
		self._register_plot_widget("spectrum", self.pltSA)
		self._plot_channel_items["spectrum"] = {
			0: [self.curveSA1, self.pirSA1, self.peakSA1],
			1: [self.curveSA2, self.pirSA2, self.peakSA2],
		}
		# --- widget: I value in time -----------------------------
		self.pltI = pg.PlotWidget(viewBox=_AxisSeparateScrollViewBox())
		self.pltI.setTitle("I value")
		self.pltI.setLabel('left',text="I value", units='')
		self.pltI.setLabel('bottom',text="Sample number", units='')
		self.curveI1=self.pltI.plot(pen='g')
		self.curveI2=self.pltI.plot(pen='c')
		self._register_plot_widget("i_value", self.pltI)
		self._plot_channel_items["i_value"] = {
			0: [self.curveI1],
			1: [self.curveI2],
		}
		# --- widget: Q value in time -----------------------------
		self.pltQ = pg.PlotWidget(viewBox=_AxisSeparateScrollViewBox())
		self.pltQ.setTitle("Q value")
		self.pltQ.setLabel('left',text="Q value", units='rad')
		self.pltQ.setLabel('bottom',text="Sample number", units='')
		self.curveQ1=self.pltQ.plot(pen='g')
		self.curveQ2=self.pltQ.plot(pen='c')
		self._register_plot_widget("q_value", self.pltQ)
		self._plot_channel_items["q_value"] = {
			0: [self.curveQ1],
			1: [self.curveQ2],
		}
		# --- widget: frequency in time -----------------------------
		self.pltFREQERR = pg.PlotWidget(viewBox=_AxisSeparateScrollViewBox())
		self.pltFREQERR.setTitle("Frequency error (Hz)")
		self.pltFREQERR.setLabel('left',text="Frequency", units='Hz')
		self.pltFREQERR.setLabel('bottom',text="Sample number", units='')
		self.curveFREQERR1=self.pltFREQERR.plot(pen='g')
		self.curveFREQERR2=self.pltFREQERR.plot(pen='c')
		self._register_plot_widget("frequency", self.pltFREQERR)
		self._plot_channel_items["frequency"] = {
			0: [self.curveFREQERR1],
			1: [self.curveFREQERR2],
		}
		#self.curveFREQERRdiff=self.pltFREQERR.plot(pen='y')
		# --- widget: Ctrl signals in time -----------------------------
		self.pltCTRL = pg.PlotWidget(viewBox=_AxisSeparateScrollViewBox())
		self.pltCTRL.setTitle("Ctrl signals")
		self.pltCTRL.setLabel('left',text="Ctrl signals", units='V')
		self.pltCTRL.setLabel('bottom',text="Sample number", units='')
		self.curveCTRL00=self.pltCTRL.plot(pen='g')
		self.curveCTRL01=self.pltCTRL.plot(pen='r')
		self.curveCTRL10=self.pltCTRL.plot(pen='c')
		self.curveCTRL11=self.pltCTRL.plot(pen='m')
		self._register_plot_widget("ctrl", self.pltCTRL)
		self._plot_channel_items["ctrl"] = {
			0: [self.curveCTRL00, self.curveCTRL01],
			1: [self.curveCTRL10, self.curveCTRL11],
		}
		if self._active_plot_key is None:
			self._active_plot_key = "spectrum"

	def _register_plot_widget(self, key: str, widget: pg.PlotWidget) -> None:
		"""Register a plot widget and track which plot is active for menu actions."""
		self._plot_widgets[key] = widget
		self._plot_autoscale_y.setdefault(key, False)
		try:
			widget.scene().sigMouseClicked.connect(
				lambda _evt, plot_key=key: self._set_active_plot(plot_key)
			)
		except Exception:
			pass

	def _set_active_plot(self, key: str) -> None:
		"""Set the active plot key (used for autoscale and export)."""
		if key in self._plot_widgets:
			self._active_plot_key = key

	def get_active_plot_key(self) -> str:
		"""Return the key of the most recently interacted plot."""
		return self._active_plot_key or "spectrum"

	def get_plot_widget(self, key: str) -> pg.PlotWidget:
		"""Return a plot widget by key."""
		return self._plot_widgets.get(key)

	def get_plot_channel_items(self, key: str):
		"""Return items grouped by channel for a plot key."""
		return self._plot_channel_items.get(key, {})

	def is_plot_autoscale_y(self, key: str) -> bool:
		"""Return whether Y autoscale is enabled for the given plot key."""
		return bool(self._plot_autoscale_y.get(key, False))

	def set_plot_autoscale_y(self, key: str, enabled: bool) -> None:
		"""Enable/disable Y autoscale for a plot."""
		plot = self._plot_widgets.get(key)
		if plot is None:
			return
		self._plot_autoscale_y[key] = bool(enabled)
		try:
			plot.enableAutoRange(axis='y', enable=bool(enabled))
		except Exception:
			vb = plot.getViewBox()
			vb.enableAutoRange(axis=pg.ViewBox.YAxis, enable=bool(enabled))

	def set_freq_plot_for_phasemeter(self, phasemeter: bool):
		"""
		Set the freq plot title/labels for phasemeter (PIR in Hz) or laser_lock (freq error).

		Parameters
		----------
		phasemeter : bool
			If True, show "Frequency readout (Hz)" (PIR readout); if False, show "Frequency error (Hz)".
		"""
		if phasemeter:
			self.pltFREQERR.setTitle("Frequency readout (Hz)")
			self.pltFREQERR.setLabel('left', text="Frequency", units='Hz')
		else:
			self.pltFREQERR.setTitle("Frequency error (Hz)")
			self.pltFREQERR.setLabel('left', text="Frequency", units='Hz')

	def set_channel_visible(self, channel: int, visible: bool) -> None:
		"""Show/hide the given channel across all plots."""
		ch = int(channel)
		for _plot_key, items_by_ch in self._plot_channel_items.items():
			items = items_by_ch.get(ch)
			if not items:
				continue
			for item in items:
				try:
					item.setVisible(bool(visible))
				except Exception:
					pass

	def set_channel_color(self, channel: int, color) -> None:
		"""Set the trace color for the given channel across all plots."""
		ch = int(channel)
		pen = pg.mkPen(color)
		brush = pg.mkBrush(color)
		for plot_key, items_by_ch in self._plot_channel_items.items():
			# Keep Ctrl plot colors (different signals) distinct.
			if plot_key == "ctrl":
				continue
			items = items_by_ch.get(ch)
			if not items:
				continue
			for item in items:
				try:
					# PlotDataItem / Curve
					if hasattr(item, "setPen"):
						item.setPen(pen)
					# ScatterPlotItem
					if hasattr(item, "setBrush"):
						item.setBrush(brush)
				except Exception:
					pass

	def apply_plot_theme(self, theme: str) -> None:
		"""
		Apply a plot theme:
		- 'dark': black background, white axes
		- 'light': white background, black axes
		"""
		theme = (theme or "dark").lower()
		if theme not in ("dark", "light"):
			theme = "dark"
		bg = "k" if theme == "dark" else "w"
		fg = "w" if theme == "dark" else "k"
		pen = pg.mkPen(fg)

		for _key, plot in self._plot_widgets.items():
			try:
				plot.setBackground(bg)
			except Exception:
				pass
			# Title color (important for light theme).
			try:
				pi = plot.getPlotItem()
				title_html = getattr(pi.titleLabel, "text", None)
				if title_html:
					pi.titleLabel.setText(title_html, color=fg)
			except Exception:
				pass
			for ax_name in ("bottom", "left"):
				try:
					ax = plot.getAxis(ax_name)
					ax.setPen(pen)
					if hasattr(ax, "setTextPen"):
						ax.setTextPen(pen)
					if hasattr(ax, "setTickPen"):
						ax.setTickPen(pen)
				except Exception:
					pass

	def reset_all_axes(self) -> None:
		"""
		Reset every plot's axes to auto-range.

		This matches the behavior of clicking the built-in "A" (auto) button in each plot,
		so plots resume normal scrolling/auto-range behavior after manual pan/zoom.
		"""
		for _key, plot in self._plot_widgets.items():
			try:
				plot.getPlotItem().autoBtnClicked()
			except Exception:
				pass

	def updateGUIs(self, vm):
		"""
		Update all plots from a PlotViewModel.

		Parameters
		----------
		vm : PlotViewModel
			View model with f, spectrum, t, i_t, q_t, etc.
		"""
		self.updateGUIpltSA(vm)
		self.updateGUIpltI(vm)
		self.updateGUIpltQ(vm)
		self.updateGUIpltFREQERR(vm)
		self.updateGUIpltCTRL(vm)

	def updateGUIpltSA(self, vm):
		"""
		Update spectrum plot, PIR vertical lines, and FFT peak markers from view model.

		PIR lines: vertical at PIR frequency (Hz), colors match channel 0 (green) / channel 1 (cyan).
		Peak markers: (freq_peak, amp_peak) from FFT; channel 0 "+", channel 1 "x".
		When beatfreq is 0 but spectrum has a peak, use client-side argmax fallback.
		"""
		self.curveSA1.setData(vm.f, vm.spectrum[0])
		self.curveSA2.setData(vm.f, vm.spectrum[1])
		# PIR vertical lines (PIR in Hz)
		pir0x = [vm.pir[0], vm.pir[0]]
		pir0y = [0.0, max(vm.spectrum[0]) if len(vm.spectrum[0]) > 0 else 0.0]
		self.pirSA1.setData(pir0x, pir0y)
		pir1x = [vm.pir[1], vm.pir[1]]
		pir1y = [0.0, max(vm.spectrum[1]) if len(vm.spectrum[1]) > 0 else 0.0]
		self.pirSA2.setData(pir1x, pir1y)
		# FFT peak markers: vm.beatfreq already has effective values (from process_tick)
		peak0 = vm.beatfreq[0]
		peak1 = vm.beatfreq[1]

		def amp_at_freq(f_arr, spec, freq):
			if len(spec) == 0 or len(f_arr) == 0:
				return 0.0
			idx = int(np.clip(np.argmin(np.abs(f_arr - freq)), 0, len(spec) - 1))
			return float(spec[idx])

		amp0 = amp_at_freq(vm.f, vm.spectrum[0], peak0)
		amp1 = amp_at_freq(vm.f, vm.spectrum[1], peak1)
		# Hide markers when no valid peak (avoids (0,0) display after reconnect)
		self.peakSA1.setData(pos=np.array([[peak0, amp0]]) if peak0 > 0 else np.empty((0, 2)))
		self.peakSA2.setData(pos=np.array([[peak1, amp1]]) if peak1 > 0 else np.empty((0, 2)))

	def _on_sa_range_changed(self, *args):
		"""
		Clamp Spectrum Analyzer view: x in [0, 125e6] Hz, y_min=0, y_range >= 100 uVpp.

		Parameters
		----------
		*args
			Ignored (slot signature from sigRangeChanged).
		"""
		if self._sa_is_clamping:
			return
		self._sa_is_clamping = True
		try:
			vb = self._sa_vb
			(x0, x1), (y0, y1) = vb.viewRange()

			# Clamp x to [0, 125e6].
			dx = x1 - x0
			if dx <= 0:
				dx = 1.0
			if x0 < self._sa_x_min_hz:
				x0 = self._sa_x_min_hz
				x1 = x0 + dx
			if x1 > self._sa_x_max_hz:
				x1 = self._sa_x_max_hz
				x0 = x1 - dx
			if x0 < self._sa_x_min_hz:
				x0 = self._sa_x_min_hz

			# Pin y_min to 0 and enforce y-range >= 100 uVpp.
			dy = y1 - y0
			if dy < self._sa_y_min_range_vpp:
				dy = self._sa_y_min_range_vpp
			y0 = 0.0
			y1 = y0 + dy

			vb.setRange(xRange=(x0, x1), yRange=(y0, y1), padding=0)
		finally:
			self._sa_is_clamping = False

	def updateGUIpltI(self, vm):
		"""
		Update I-value vs time plot from view model.

		Parameters
		----------
		vm : PlotViewModel
			View model with t and i_t.
		"""
		self.curveI1.setData(vm.t, vm.i_t[0])
		self.curveI2.setData(vm.t, vm.i_t[1])

	def updateGUIpltQ(self, vm):
		"""
		Update Q-value vs time plot from view model.

		Parameters
		----------
		vm : PlotViewModel
			View model with t and q_t.
		"""
		self.curveQ1.setData(vm.t, vm.q_t[0])
		self.curveQ2.setData(vm.t, vm.q_t[1])

	def updateGUIpltFREQERR(self, vm):
		"""
		Update frequency plot vs time from view model.

		Parameters
		----------
		vm : PlotViewModel
			View model with t and freq_plot_t.
		"""
		self.curveFREQERR1.setData(vm.t, vm.freq_plot_t[0])
		self.curveFREQERR2.setData(vm.t, vm.freq_plot_t[1])

	def updateGUIpltCTRL(self, vm):
		"""
		Update control signals (piezo, temp) vs time plot from view model.

		Parameters
		----------
		vm : PlotViewModel
			View model with t, piezo_t, and temp_t.
		"""
		self.curveCTRL00.setData(vm.t, vm.piezo_t[0])
		self.curveCTRL01.setData(vm.t, vm.temp_t[0])
		self.curveCTRL10.setData(vm.t, vm.piezo_t[1])
		self.curveCTRL11.setData(vm.t, vm.temp_t[1])
