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

import time
from collections import deque

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

import global_params as glp
import data_models as aux
import widgets as st
import gui
import frame_schema
import rp_protocol


def _make_group_box_font() -> QtGui.QFont:
    """Return a font matching standard label size without bold."""
    base_font = QtWidgets.QLabel().font()
    base_font.setBold(False)
    return base_font


class Session:
    """
    Holds connection, dataset, widgets, and plot state; runs the processing loop.

    Layout builds UI from session.widgets and session.gui; timer calls
    session.process_tick().
    """

    def __init__(self):
        """
        Create session with no connection, empty dataset, widgets, and plot state.

        No parameters. Initializes connection=None, DataPackage, WidgetList,
        GuiLayout, and runtime stats (frame_count, fps, parse_error_count).
        """
        self.connection = None
        self.dataset = aux.DataPackage()
        self.widgets = st.WidgetList(None)
        self.gui = gui.GuiLayout()
        self.frame_count = 0
        self.parse_error_count = 0
        self.fps = 0.0
        self._fps_window_s = 2.0
        self._frame_times = deque()
        self._warnings_widget = None
        self._warned_fallback_ch0 = False
        self._warned_fallback_ch1 = False
        self.render_paused = False

    def is_connected(self) -> bool:
        """
        Report whether a connection is currently open.

        Returns
        -------
        bool
            True if connection is set and connected, False otherwise.
        """
        return self.connection is not None and self.connection.is_connected()

    def disconnect(self) -> None:
        """
        Close connection and clear widgets' socket.

        Safe to call when already disconnected. Sets connection to None and
        updates all widget sockets to None. Clears dataset to avoid stale
        display on reconnect.
        """
        if self.connection is not None:
            self.connection.disconnect()
            self.connection = None
        self.widgets.set_socket(None)
        self.dataset.clear()

    def set_connection(self, connection) -> None:
        """
        Set the RedPitaya connection and update widgets' socket.

        Parameters
        ----------
        connection : RPConnection or None
            Active connection or None (disconnected).
        """
        self.connection = connection
        self.widgets.set_socket(connection.socket if connection else None)
        if connection is not None:
            self._warned_fallback_ch0 = False
            self._warned_fallback_ch1 = False
            connection.set_log_callback(self.log_warning)

    def log_warning(self, msg: str) -> None:
        """
        Append a warning or debug message to the warnings text box.

        Parameters
        ----------
        msg : str
            Message to append (with timestamp).
        """
        if self._warnings_widget is None:
            return
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self._warnings_widget.appendPlainText(f"[{ts}] {msg}")

    def build_plot_view_model(self) -> aux.PlotViewModel:
        """
        Build plot view model with mode-specific frequency data.

        Uses PIR readout for phasemeter mode, and PIR minus reference frequency
        for laser-lock mode.
        """
        is_phasemeter = (
            self.connection is not None
            and self.connection.server_variant == rp_protocol.RP_CAP_PHASEMETER
        )
        ref_freqs = [
            self.widgets.freq_ref_loop_0.box.value(),
            self.widgets.freq_ref_loop_1.box.value(),
        ]
        freq_plot_t = aux.compute_freq_plot_t(self.dataset, is_phasemeter, ref_freqs)
        return aux.build_plot_view_model(self.dataset, freq_plot_t=freq_plot_t)

    def process_tick(self) -> None:
        """
        Read one frame, update dataset and plots, run widget processing.

        No-op if disconnected. On parse error increments parse_error_count.
        On closed/os_error disconnects. Updates frame_count and fps.

        Returns
        -------
        None
        """
        if self.connection is None:
            return
        data = self.connection.read_frame(timeout_s=0.0)
        if data is None:
            status = self.connection.last_read_status
            if status == "parse_error":
                self.parse_error_count += 1
            elif status in ("closed", "os_error"):
                self.disconnect()
            return
        if len(data) != frame_schema.FRAME_SIZE_DOUBLES:
            self.parse_error_count += 1
            return
        self.frame_count += 1
        now = time.monotonic()
        self._frame_times.append(now)
        cutoff = now - self._fps_window_s
        while self._frame_times and self._frame_times[0] < cutoff:
            self._frame_times.popleft()
        if len(self._frame_times) >= 2:
            span = self._frame_times[-1] - self._frame_times[0]
            self.fps = (len(self._frame_times) - 1) / span if span > 0 else 0.0
        else:
            self.fps = 0.0
        self.dataset.substitute_data(data)
        self.dataset.update_t()
        self.widgets.beatfreq = self.dataset.beatfreq
        # Override with effective beatfreq when server sends 0 (Reacquire + display)
        eff0, fallback0 = aux.effective_beatfreq(
            self.dataset.spectrum[0], self.dataset.beatfreq[0], self.dataset.f
        )
        eff1, fallback1 = aux.effective_beatfreq(
            self.dataset.spectrum[1], self.dataset.beatfreq[1], self.dataset.f
        )
        if fallback0 and not self._warned_fallback_ch0:
            self.log_warning("Ch1: client-side peak fallback (server beatfreq=0 or wrong)")
            self._warned_fallback_ch0 = True
        if fallback1 and not self._warned_fallback_ch1:
            self.log_warning("Ch2: client-side peak fallback (server beatfreq=0 or wrong)")
            self._warned_fallback_ch1 = True
        self.dataset.beatfreq[0] = eff0
        self.dataset.beatfreq[1] = eff1
        self.widgets.beatfreq[0] = eff0
        self.widgets.beatfreq[1] = eff1
        plot_vm = self.build_plot_view_model()
        if not self.render_paused:
            self.gui.updateGUIs(plot_vm)
        self.widgets.processing(self.dataset)


class MainLayout():
    def __init__(self, session):
        """
        Build main window layout: top bar + splitter (controls | plots).

        Parameters
        ----------
        session : Session
            Session holding connection, dataset, widgets, and gui (plot state).
        """
        self.session = session

        group_box_font = _make_group_box_font()

        # --- New layout: single window, resizable splitter -------------
        # Left pane: all controls visible (readout + laser lock + data)
        # Right pane: 5 plots always visible (5 rows x 1 column)

        # Left pane (controls)
        self.readout_setting = ReadoutSettingLayout(self.session.widgets)
        self.ctrl_setting = LaserLockSettingLayout(self.session.widgets)

        readout_controls_widget = QtWidgets.QWidget()
        readout_controls_widget.setLayout(self.readout_setting)
        self.ctrl_controls_widget = QtWidgets.QWidget()
        self.ctrl_controls_widget.setLayout(self.ctrl_setting)

        # Data Logger (moved to bottom of pane)
        self.data_logger_group = QtWidgets.QGroupBox("Data Logger")
        self.data_logger_group.setFont(group_box_font)
        data_layout = QtWidgets.QVBoxLayout()
        data_layout.addWidget(self.session.widgets.data_logger_controls_widget)
        data_layout.addWidget(self.session.widgets.data_logger_record_length_fields_widget)
        data_layout.addWidget(self.session.widgets.label_record_length_note)
        self.data_logger_group.setLayout(data_layout)

        # Plots configuration (above Data Logger)
        self.plots_group = QtWidgets.QGroupBox("Plots")
        self.plots_group.setFont(group_box_font)
        plots_layout = QtWidgets.QGridLayout()
        plots_layout.setContentsMargins(8, 8, 8, 8)
        plots_layout.setHorizontalSpacing(10)
        plots_layout.setVerticalSpacing(6)

        self.plot_ch1_visible_cb = QtWidgets.QCheckBox("Ch1")
        self.plot_ch2_visible_cb = QtWidgets.QCheckBox("Ch2")
        self.plot_ch1_visible_cb.setChecked(True)
        self.plot_ch2_visible_cb.setChecked(True)
        self.plot_ch1_visible_cb.toggled.connect(lambda checked: self.session.gui.set_channel_visible(0, checked))
        self.plot_ch2_visible_cb.toggled.connect(lambda checked: self.session.gui.set_channel_visible(1, checked))
        plots_layout.addWidget(QtWidgets.QLabel("Show channels:"), 0, 0)
        plots_layout.addWidget(self.plot_ch1_visible_cb, 0, 1)
        plots_layout.addWidget(self.plot_ch2_visible_cb, 0, 2)

        def _make_color_combo(default_key: str):
            combo = QtWidgets.QComboBox()
            combo.setIconSize(QtCore.QSize(12, 12))
            for label, key in [
                ("Green", "g"),
                ("Cyan", "c"),
                ("Red", "r"),
                ("Magenta", "m"),
                ("Yellow", "y"),
                ("White", "w"),
                ("Blue", "b"),
                ("Black", "k"),
            ]:
                # Add a colored square icon next to the label.
                try:
                    qcolor = pg.mkColor(key)
                    pix = QtGui.QPixmap(12, 12)
                    pix.fill(qcolor)
                    icon = QtGui.QIcon(pix)
                except Exception:
                    icon = QtGui.QIcon()
                combo.addItem(icon, label, key)
            for idx in range(combo.count()):
                if combo.itemData(idx) == default_key:
                    combo.setCurrentIndex(idx)
                    break
            return combo

        self.plot_ch1_color_combo = _make_color_combo("g")
        self.plot_ch2_color_combo = _make_color_combo("c")
        self.plot_ch1_color_combo.currentIndexChanged.connect(
            lambda _idx: self.session.gui.set_channel_color(0, self.plot_ch1_color_combo.currentData())
        )
        self.plot_ch2_color_combo.currentIndexChanged.connect(
            lambda _idx: self.session.gui.set_channel_color(1, self.plot_ch2_color_combo.currentData())
        )
        plots_layout.addWidget(QtWidgets.QLabel("Ch1 color:"), 1, 0)
        plots_layout.addWidget(self.plot_ch1_color_combo, 1, 1, 1, 2)
        plots_layout.addWidget(QtWidgets.QLabel("Ch2 color:"), 2, 0)
        plots_layout.addWidget(self.plot_ch2_color_combo, 2, 1, 1, 2)

        self.plot_theme_combo = QtWidgets.QComboBox()
        self.plot_theme_combo.addItem("Dark", "dark")
        self.plot_theme_combo.addItem("Light", "light")
        self.plot_theme_combo.setCurrentIndex(0)
        self.plot_theme_combo.currentIndexChanged.connect(
            lambda _idx: self.session.gui.apply_plot_theme(self.plot_theme_combo.currentData())
        )
        self.reset_axes_btn = QtWidgets.QPushButton("Reset Axes")
        self.reset_axes_btn.clicked.connect(self.session.gui.reset_all_axes)
        plots_layout.addWidget(QtWidgets.QLabel("Background:"), 3, 0)
        plots_layout.addWidget(self.plot_theme_combo, 3, 1)
        plots_layout.addWidget(self.reset_axes_btn, 3, 2)

        plots_layout.setColumnStretch(3, 1)
        self.plots_group.setLayout(plots_layout)

        # Warnings / debug log at bottom of left pane
        self.warnings_group = QtWidgets.QGroupBox("Warnings & Log")
        self.warnings_group.setFont(group_box_font)
        self.warnings_edit = QtWidgets.QPlainTextEdit()
        self.warnings_edit.setReadOnly(True)
        self.warnings_edit.setMaximumHeight(120)
        self.warnings_edit.setPlaceholderText("Warnings and debug info appear here.")
        warnings_layout = QtWidgets.QVBoxLayout()
        warnings_layout.addWidget(self.warnings_edit)
        self.warnings_group.setLayout(warnings_layout)
        self.session._warnings_widget = self.warnings_edit

        self.controls_widget = QtWidgets.QWidget()
        controls_vbox = QtWidgets.QVBoxLayout()
        controls_vbox.setContentsMargins(0, 0, 0, 0)
        controls_vbox.setSpacing(6)
        controls_vbox.addWidget(readout_controls_widget)
        controls_vbox.addWidget(self.ctrl_controls_widget)
        controls_vbox.addWidget(self.plots_group)
        controls_vbox.addWidget(self.data_logger_group)
        controls_vbox.addWidget(self.warnings_group)
        controls_vbox.addStretch(1)
        self.controls_widget.setLayout(controls_vbox)

        # Right pane (plots)
        self.plots_widget = QtWidgets.QWidget()
        self.plots_grid = QtWidgets.QGridLayout()
        self.plots_grid.setContentsMargins(0, 0, 0, 0)
        self.plots_grid.setSpacing(6)

        self.plots_grid.addWidget(self.session.gui.pltSA, 0, 0)
        self.plots_grid.addWidget(self.session.gui.pltI, 1, 0)
        self.plots_grid.addWidget(self.session.gui.pltQ, 2, 0)
        self.plots_grid.addWidget(self.session.gui.pltFREQERR, 3, 0)
        self.plots_grid.addWidget(self.session.gui.pltCTRL, 4, 0)

        # Give Spectrum Analyzer a bit more space than the other plots.
        self.plots_grid.setRowStretch(0, 2)
        self.plots_grid.setRowStretch(1, 1)
        self.plots_grid.setRowStretch(2, 1)
        self.plots_grid.setRowStretch(3, 1)
        self.plots_grid.setRowStretch(4, 1)
        self.plots_grid.setColumnStretch(0, 1)

        self.plots_widget.setLayout(self.plots_grid)

        self._plot_rows = {
            "spectrum": 0,
            "i_value": 1,
            "q_value": 2,
            "frequency": 3,
            "ctrl": 4,
        }
        self._plot_widgets = {
            "spectrum": self.session.gui.pltSA,
            "i_value": self.session.gui.pltI,
            "q_value": self.session.gui.pltQ,
            "frequency": self.session.gui.pltFREQERR,
            "ctrl": self.session.gui.pltCTRL,
        }
        self._plot_row_stretch_default = {
            0: 2,
            1: 1,
            2: 1,
            3: 1,
            4: 1,
        }
        self._plot_visibility = {key: True for key in self._plot_widgets.keys()}
        self._default_plot_visibility = None
        self._default_controls_visible = None
        self._default_warnings_visible = None
        self._default_splitter_sizes = None
        self._splitter_sizes_before_hide = None

        # Main splitter (user-resizable divider)
        self.main_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.main_splitter.addWidget(self.controls_widget)
        self.main_splitter.addWidget(self.plots_widget)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)

        # Reacquire: replace default handlers so we control order (sync beatfreq before reset).
        # Old client calls use_peakfreq on BOTH press and release; we match that.
        try:
            self.session.widgets.pushButton_reset_a.pressed.disconnect(
                self.session.widgets.send_activate_reset_pll_dsp
            )
            self.session.widgets.pushButton_reset_a.released.disconnect(
                self.session.widgets.send_release_reset_pll_dsp
            )
        except TypeError:
            pass
        self.session.widgets.pushButton_reset_a.pressed.connect(self._on_reacquire_press)
        self.session.widgets.pushButton_reset_a.released.connect(self._on_reacquire_release)

        # Apply default (disconnected) UI mode immediately on startup.
        self.apply_server_variant()

    def _on_reacquire_press(self) -> None:
        """Sync beatfreq from dataset (with effective fallback), send reset hold (matches old client)."""
        self.session.widgets.beatfreq = self.session.dataset.beatfreq.copy()
        eff0, _ = aux.effective_beatfreq(
            self.session.dataset.spectrum[0], self.session.dataset.beatfreq[0],
            self.session.dataset.f
        )
        eff1, _ = aux.effective_beatfreq(
            self.session.dataset.spectrum[1], self.session.dataset.beatfreq[1],
            self.session.dataset.f
        )
        self.session.widgets.beatfreq[0] = eff0
        self.session.widgets.beatfreq[1] = eff1
        self.session.widgets.send_activate_reset_pll_dsp()

    def _on_reacquire_release(self) -> None:
        """Send reset release, set Initial Freq to peak again, then clear plots (matches old client)."""
        self.session.widgets.send_release_reset_pll_dsp()
        self.session.widgets.use_peakfreq0()
        self.session.widgets.use_peakfreq1()
        self.session.dataset.clear()

    def reacquire(self) -> None:
        """Perform a full Reacquire press/release sequence."""
        self._on_reacquire_press()
        self._on_reacquire_release()

    def is_connected(self) -> bool:
        """
        Report whether the session has an open connection.

        Returns
        -------
        bool
            True if session is connected, False otherwise.
        """
        return self.session.is_connected()

    def disconnect(self) -> None:
        """
        Disconnect session and clear widgets' socket.

        Delegates to session.disconnect(). Refreshes plots to show cleared state.
        Safe when already disconnected.
        """
        self.session.disconnect()
        plot_vm = self.session.build_plot_view_model()
        self.session.gui.updateGUIs(plot_vm)
        # Re-apply mode-specific visibility (defaults to phasemeter when disconnected).
        self.apply_server_variant()

    def set_connection(self, connection) -> None:
        """
        Set the RP connection and update widgets' socket.

        Hides laser-lock controls when connected to a phasemeter-only server.

        Parameters
        ----------
        connection : RPConnection or None
            Active connection or None.
        """
        self.session.set_connection(connection)
        self.apply_server_variant()

    def apply_server_variant(self) -> None:
        """Apply visibility and labels based on current server variant."""
        # Default to reduced phasemeter UI when disconnected; only show full controls
        # when a connected server explicitly advertises laser_lock.
        server_variant = (
            self.session.connection.server_variant
            if self.session.connection is not None
            else rp_protocol.RP_CAP_PHASEMETER
        )
        if server_variant == rp_protocol.RP_CAP_PHASEMETER:
            self.ctrl_controls_widget.setVisible(False)
            self.session.gui.pltCTRL.setVisible(False)
            self.plots_grid.setRowStretch(4, 0)  # Ctrl row gets no space; others fill vertically
            self.session.gui.set_freq_plot_for_phasemeter(True)
        else:
            self.ctrl_controls_widget.setVisible(True)
            self.session.gui.pltCTRL.setVisible(True)
            self.plots_grid.setRowStretch(4, 1)
            self.session.gui.set_freq_plot_for_phasemeter(False)

    def is_phasemeter_mode(self) -> bool:
        """Return True when in phasemeter mode (default when disconnected)."""
        if self.session.connection is None:
            return True
        return self.session.connection.server_variant == rp_protocol.RP_CAP_PHASEMETER

    def capture_default_layout(self) -> None:
        """Capture default splitter sizes and plot visibility once."""
        if self._default_splitter_sizes is None:
            self._default_splitter_sizes = self.main_splitter.sizes()
        if self._default_plot_visibility is None:
            self._default_plot_visibility = {
                key: widget.isVisible() for key, widget in self._plot_widgets.items()
            }
        if self._default_controls_visible is None:
            self._default_controls_visible = self.controls_widget.isVisible()
        if self._default_warnings_visible is None:
            self._default_warnings_visible = self.warnings_group.isVisible()

    def set_controls_visible(self, visible: bool) -> None:
        """Show/hide the entire left control panel."""
        if visible and not self.controls_widget.isVisible():
            self.controls_widget.setVisible(True)
            if self._splitter_sizes_before_hide:
                self.main_splitter.setSizes(self._splitter_sizes_before_hide)
        elif not visible and self.controls_widget.isVisible():
            self._splitter_sizes_before_hide = self.main_splitter.sizes()
            self.controls_widget.setVisible(False)

    def set_warnings_visible(self, visible: bool) -> None:
        """Show/hide the warnings/log group box."""
        self.warnings_group.setVisible(bool(visible))

    def set_plot_visible(self, key: str, visible: bool) -> None:
        """Show/hide a plot panel by key."""
        if key not in self._plot_widgets:
            return
        widget = self._plot_widgets[key]
        widget.setVisible(bool(visible))
        row = self._plot_rows.get(key)
        if row is not None:
            self.plots_grid.setRowStretch(
                row, self._plot_row_stretch_default.get(row, 1) if visible else 0
            )
        self._plot_visibility[key] = bool(visible)

    def is_plot_visible(self, key: str) -> bool:
        """Return whether the plot panel is currently visible."""
        widget = self._plot_widgets.get(key)
        return bool(widget and widget.isVisible())

    def reset_layout(self) -> None:
        """Restore default splitter sizes and visible panels."""
        if self._default_plot_visibility:
            for key, visible in self._default_plot_visibility.items():
                self.set_plot_visible(key, visible)
        if self._default_splitter_sizes:
            self.main_splitter.setSizes(self._default_splitter_sizes)
        if self._default_controls_visible is not None:
            self.set_controls_visible(self._default_controls_visible)
        else:
            self.set_controls_visible(True)
        if self._default_warnings_visible is not None:
            self.set_warnings_visible(self._default_warnings_visible)
        else:
            self.set_warnings_visible(True)
        self.apply_server_variant()

    def set_render_paused(self, paused: bool) -> None:
        """Pause/unpause plot rendering without stopping acquisition."""
        self.session.render_paused = bool(paused)

    def is_render_paused(self) -> bool:
        """Return True when plot rendering is paused."""
        return bool(self.session.render_paused)

    @property
    def dataset(self):
        """
        Current dataset (DataPackage) from session.

        Returns
        -------
        DataPackage
            The session's dataset.
        """
        return self.session.dataset

    @property
    def widgets(self):
        """
        Widget list (controls) from session.

        Returns
        -------
        WidgetList
            The session's widget list.
        """
        return self.session.widgets

    @property
    def frame_count(self):
        """
        Total frames received this session.

        Returns
        -------
        int
            Cumulative frame count.
        """
        return self.session.frame_count

    @property
    def fps(self):
        """
        Frames per second (rolling window).

        Returns
        -------
        float
            FPS over the last ~2 seconds.
        """
        return self.session.fps

    @property
    def parse_error_count(self):
        """
        Number of parse errors this session.

        Returns
        -------
        int
            Cumulative parse error count.
        """
        return self.session.parse_error_count


class ReadoutSettingLayout(QtWidgets.QGridLayout):
	def __init__(self, widgetls):
		"""
		Build phasemeter (PLL) controls layout for two channels from widget list.

		Parameters
		----------
		widgetls : WidgetList
			Widget list providing ifreq, gain_pll_p/i, and reset buttons.
		"""
		super().__init__()

		group_box_font = _make_group_box_font()

		# --- PLL1 -------------------------------------
		PLL1 = QtWidgets.QGroupBox("Channel 1 Phasemeter")
		PLL1.setFont(group_box_font)
		pll1_layout = QtWidgets.QVBoxLayout()
		pll1_layout.addWidget(widgetls.ifreq_0.label)
		pll1_layout.addWidget(widgetls.ifreq_0.box)  
		pll1_layout.addWidget(widgetls.gain_pll_p_0.label)
		pll1_layout.addWidget(widgetls.gain_pll_p_0.box)  
		pll1_layout.addWidget(widgetls.gain_pll_i_0.label)
		pll1_layout.addWidget(widgetls.gain_pll_i_0.box)  
		pll1_layout.addWidget(widgetls.pushButton_copy_settings_ch2)
		PLL1.setLayout(pll1_layout)
		# --- PLL2 -------------------------------------
		PLL2 = QtWidgets.QGroupBox("Channel 2 Phasemeter")
		PLL2.setFont(group_box_font)
		pll2_layout = QtWidgets.QVBoxLayout()
		pll2_layout.addWidget(widgetls.ifreq_1.label)
		pll2_layout.addWidget(widgetls.ifreq_1.box)  
		pll2_layout.addWidget(widgetls.gain_pll_p_1.label)
		pll2_layout.addWidget(widgetls.gain_pll_p_1.box)  
		pll2_layout.addWidget(widgetls.gain_pll_i_1.label)
		pll2_layout.addWidget(widgetls.gain_pll_i_1.box)  
		# Move "Reacquire" button here (was under Data).
		pll2_layout.addWidget(widgetls.pushButton_reset_a)
		PLL2.setLayout(pll2_layout)

		# --- add to layout -------------------------------------
		self.addWidget(PLL1, 0, 0)
		self.addWidget(PLL2, 0, 1)



class LaserLockSettingLayout(QtWidgets.QGridLayout):
	def __init__(self, widgetls):
		"""
		Build laser-lock controls (PZT/TEMP servos, reference freq) for two channels.

		Parameters
		----------
		widgetls : WidgetList
			Widget list providing piezo/temp/freq controls and buttons.
		"""
		super().__init__()

		group_box_font = _make_group_box_font()

		# --- PLL1 -------------------------------------
		# *** PZT ********************************
		PLL1_PZT = QtWidgets.QGroupBox("Channel 1 PZT Servo")
		PLL1_PZT.setFont(group_box_font)
		pll1_pzt = QtWidgets.QVBoxLayout()
		pll1_pzt.addWidget(widgetls.piezo_switch_loop_0.label)
		pll1_pzt.addWidget(widgetls.piezo_switch_loop_0.box)
		pll1_pzt.addWidget(widgetls.piezo_sign_loop_0.label)
		pll1_pzt.addWidget(widgetls.piezo_sign_loop_0.box)
		pll1_pzt.addWidget(widgetls.piezo_offset_0.label)
		pll1_pzt.addWidget(widgetls.piezo_offset_0.box)
		pll1_pzt.addWidget(widgetls.piezo_gain_I_0.label)
		pll1_pzt.addWidget(widgetls.piezo_gain_I_0.box)
		pll1_pzt.addWidget(widgetls.piezo_gain_II_0.label)
		pll1_pzt.addWidget(widgetls.piezo_gain_II_0.box)
		PLL1_PZT.setLayout(pll1_pzt)
		# *** Temps ********************************
		PLL1_TEMP = QtWidgets.QGroupBox("Channel 1 TEMP Servo")
		PLL1_TEMP.setFont(group_box_font)
		pll1_temp = QtWidgets.QVBoxLayout()
		pll1_temp.addWidget(widgetls.temp_switch_loop_0.label)
		pll1_temp.addWidget(widgetls.temp_switch_loop_0.box)
		pll1_temp.addWidget(widgetls.temp_sign_loop_0.label)
		pll1_temp.addWidget(widgetls.temp_sign_loop_0.box)
		pll1_temp.addWidget(widgetls.temp_offset_0.label)
		pll1_temp.addWidget(widgetls.temp_offset_0.box)
		pll1_temp.addWidget(widgetls.temp_gain_P_0.label)
		pll1_temp.addWidget(widgetls.temp_gain_P_0.box)
		pll1_temp.addWidget(widgetls.temp_gain_I_0.label)
		pll1_temp.addWidget(widgetls.temp_gain_I_0.box)
		PLL1_TEMP.setLayout(pll1_temp)
		# *** Freq ********************************
		PLL1_FREQ = QtWidgets.QGroupBox("Channel 1 Reference")
		PLL1_FREQ.setFont(group_box_font)
		pll1_freq = QtWidgets.QGridLayout()
		pll1_freq.addWidget(widgetls.freq_ref_loop_0.label, 0,0)
		pll1_freq.addWidget(widgetls.freq_ref_loop_0.box, 1,0)
		pll1_freq.addWidget(widgetls.freq_noise_floor_0.label, 2,0)
		pll1_freq.addWidget(widgetls.freq_noise_floor_0.box, 3,0)
		pll1_freq.addWidget(widgetls.freq_noise_corner_0.label, 2,1)
		pll1_freq.addWidget(widgetls.freq_noise_corner_0.box, 3,1)
		PLL1_FREQ.setLayout(pll1_freq)

		# --- PLL2 -------------------------------------
		# *** PZT ********************************
		PLL2_PZT = QtWidgets.QGroupBox("Channel 2 PZT Servo")
		PLL2_PZT.setFont(group_box_font)
		pll2_pzt = QtWidgets.QVBoxLayout()
		pll2_pzt.addWidget(widgetls.piezo_switch_loop_1.label)
		pll2_pzt.addWidget(widgetls.piezo_switch_loop_1.box)
		pll2_pzt.addWidget(widgetls.piezo_sign_loop_1.label)
		pll2_pzt.addWidget(widgetls.piezo_sign_loop_1.box)
		pll2_pzt.addWidget(widgetls.piezo_offset_1.label)
		pll2_pzt.addWidget(widgetls.piezo_offset_1.box)
		pll2_pzt.addWidget(widgetls.piezo_gain_I_1.label)
		pll2_pzt.addWidget(widgetls.piezo_gain_I_1.box)
		pll2_pzt.addWidget(widgetls.piezo_gain_II_1.label)
		pll2_pzt.addWidget(widgetls.piezo_gain_II_1.box)
		PLL2_PZT.setLayout(pll2_pzt)
		# *** Temps ********************************
		PLL2_TEMP = QtWidgets.QGroupBox("Channel 2 TEMP Servo")
		PLL2_TEMP.setFont(group_box_font)
		pll2_temp = QtWidgets.QVBoxLayout()
		pll2_temp.addWidget(widgetls.temp_switch_loop_1.label)
		pll2_temp.addWidget(widgetls.temp_switch_loop_1.box)
		pll2_temp.addWidget(widgetls.temp_sign_loop_1.label)
		pll2_temp.addWidget(widgetls.temp_sign_loop_1.box)
		pll2_temp.addWidget(widgetls.temp_offset_1.label)
		pll2_temp.addWidget(widgetls.temp_offset_1.box)
		pll2_temp.addWidget(widgetls.temp_gain_P_1.label)
		pll2_temp.addWidget(widgetls.temp_gain_P_1.box)
		pll2_temp.addWidget(widgetls.temp_gain_I_1.label)
		pll2_temp.addWidget(widgetls.temp_gain_I_1.box)
		PLL2_TEMP.setLayout(pll2_temp)
		# *** Freq ********************************
		PLL2_FREQ = QtWidgets.QGroupBox("Channel 2 Reference")
		PLL2_FREQ.setFont(group_box_font)
		pll2_freq = QtWidgets.QGridLayout()
		pll2_freq.addWidget(widgetls.freq_ref_loop_1.label, 0,0)
		pll2_freq.addWidget(widgetls.freq_ref_loop_1.box, 1,0)
		pll2_freq.addWidget(widgetls.freq_noise_floor_1.label, 2,0)
		pll2_freq.addWidget(widgetls.freq_noise_floor_1.box, 3,0)
		pll2_freq.addWidget(widgetls.freq_noise_corner_1.label, 2,1)
		pll2_freq.addWidget(widgetls.freq_noise_corner_1.box, 3,1)
		PLL2_FREQ.setLayout(pll2_freq)

		# --- add to layout -------------------------------------
		self.addWidget(PLL1_PZT, 0, 0)
		self.addWidget(PLL1_TEMP, 0, 1)
		self.addWidget(PLL2_PZT, 0, 2)
		self.addWidget(PLL2_TEMP, 0, 3)
		self.addWidget(PLL1_FREQ, 1, 0, 1, 2)
		self.addWidget(PLL2_FREQ, 1, 2, 1, 2)
		self.addWidget(widgetls.pushButton_open_pll_0, 2, 0, 1, 2)
		self.addWidget(widgetls.pushButton_open_pll_1, 2, 2, 1, 2)
		self.setColumnStretch(0, 1)
		self.setColumnStretch(1, 1)
		self.setColumnStretch(2, 1)
		self.setColumnStretch(3, 1)


