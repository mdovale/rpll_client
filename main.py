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
import sys
import os
import ipaddress
import re
from pathlib import Path
from typing import Iterable, Optional
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

import acquire as acq
import global_params as glp
import data_models as aux
import widgets as st
import gui
import layout as ly
import rp_protocol


def _is_valid_host(host: str) -> bool:
    """Return True for IPv4 addresses or simple hostnames."""
    if not host:
        return False
    try:
        ipaddress.IPv4Address(host)
        return True
    except Exception:
        pass
    return bool(re.match(r"^[A-Za-z0-9][A-Za-z0-9.-]*$", host))


class MainWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        """
        Create main window widget (top bar and layout placeholder until registerLayout).

        Parameters
        ----------
        parent : QWidget or None, optional
            Parent widget. Default is None.
        """
        super(MainWidget, self).__init__(parent)
        self._layout = None
        self._ip_settings_key = "last_ip"
        self._last_phasemeter_mode = False

        # --- top bar widgets (initialized in registerLayout) ----------
        self.ip_input = None
        self.connect_button = None
        self.status_indicator = None
        self.health_indicators = None
        self.health_indicator_widgets = None
        self.frames_label = None
        self.fps_label = None
        self.parse_errors_label = None

    def registerLayout(self, layout, default_ip: str):
        """
        Set the layout and build top bar (IP, Connect, status, stats) and main splitter.

        Parameters
        ----------
        layout : MainLayout
            Layout providing main_splitter and connection API.
        default_ip : str
            Default IP shown in the IP field if no saved IP exists.
        """
        self._layout = layout

        # --- top bar --------------------------------------------------
        top_bar = QtWidgets.QWidget()
        top_bar_layout = QtWidgets.QHBoxLayout()
        top_bar_layout.setContentsMargins(6, 6, 6, 6)
        top_bar_layout.setSpacing(10)

        top_bar_layout.addWidget(QtWidgets.QLabel("RedPitaya Host"))

        self.ip_input = QtWidgets.QLineEdit()
        self.ip_input.setPlaceholderText("IP address or hostname (e.g. 10.0.0.2)")
        self.ip_input.setFixedWidth(180)
        self.ip_input.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

        # Restore last used IP if available.
        settings = QtCore.QSettings("rpll", "gui")
        last_ip = settings.value(self._ip_settings_key, "", type=str)
        self.ip_input.setText(last_ip or default_ip)
        top_bar_layout.addWidget(self.ip_input)

        self.connect_button = QtWidgets.QPushButton("Connect")
        self.connect_button.clicked.connect(self._on_connect_clicked)
        top_bar_layout.addWidget(self.connect_button)

        top_bar_layout.addSpacing(8)

        top_bar_layout.addWidget(QtWidgets.QLabel("Connection"))
        self.status_indicator = QtWidgets.QLabel()
        self.status_indicator.setFixedSize(12, 12)
        self.status_indicator.setStyleSheet(
            "background-color: #cc0000; border: 1px solid #333; border-radius: 6px;"
        )
        top_bar_layout.addWidget(self.status_indicator)

        self.health_indicators = {}
        self.health_indicator_widgets = {}
        for key, label in [
            ("fft", "FFT"),
            ("i_value", "I value"),
            ("q_value", "Q value"),
            ("freq_readout", "Frequency readout (Hz)"),
            ("freq_error", "Frequency error (Hz)"),
            ("ctrl", "Control signals"),
        ]:
            widget = self._build_health_indicator(label, key)
            self.health_indicator_widgets[key] = widget
            top_bar_layout.addWidget(widget)

        top_bar_layout.addStretch(1)

        # --- runtime stats -------------------------------------------
        self.frames_label = QtWidgets.QLabel("Frames: 0")
        self.fps_label = QtWidgets.QLabel("FPS: 0.0")
        self.parse_errors_label = QtWidgets.QLabel("Parse errors: 0")
        top_bar_layout.addWidget(self.frames_label)
        top_bar_layout.addWidget(self.fps_label)
        top_bar_layout.addWidget(self.parse_errors_label)

        top_bar.setLayout(top_bar_layout)

        # --- main layout: top bar + splitter --------------------------
        vbox = QtWidgets.QVBoxLayout()
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        vbox.addWidget(top_bar)
        vbox.addWidget(layout.main_splitter, 1)
        self.setLayout(vbox)

        self._refresh_connection_ui()

    def _window_title_base(self) -> str:
        """
        Return the window title base based on server mode.

        Phasemeter servers use "RedPitaya Phasemeter"; laser-lock servers use
        "RedPitaya Laser Lock". Defaults to laser-lock when disconnected.
        """
        if self._layout and self._layout.is_phasemeter_mode():
            return "RedPitaya Phasemeter"
        return "RedPitaya Laser Lock"

    def _set_window_title(self, suffix: str) -> None:
        """Set window title using the current mode base plus suffix."""
        self.window().setWindowTitle(f"{self._window_title_base()}{suffix}")

    def _set_indicator_connected(self, is_connected: bool) -> None:
        """
        Set status indicator color: green if connected, red otherwise.

        Parameters
        ----------
        is_connected : bool
            True for green (connected), False for red (disconnected).

        Returns
        -------
        None
        """
        if self.status_indicator is None:
            return
        color = "#00aa00" if is_connected else "#cc0000"
        self.status_indicator.setStyleSheet(self._indicator_style(color))

    def _refresh_connection_ui(self) -> None:
        """
        Update Connect/Disconnect button text and status indicator from layout.

        Reads connection state from layout and updates button text and
        status indicator color accordingly.

        Returns
        -------
        None
        """
        is_connected = bool(self._layout and self._layout.is_connected())
        if self.connect_button is not None:
            self.connect_button.setText("Disconnect" if is_connected else "Connect")
        self._set_indicator_connected(is_connected)

    def _indicator_style(self, color: str) -> str:
        """Build the style string for a small colored indicator."""
        return f"background-color: {color}; border: 1px solid #333; border-radius: 6px;"

    def _build_health_indicator(self, label: str, key: str) -> QtWidgets.QWidget:
        """
        Create a label + colored indicator widget and register it by key.

        Parameters
        ----------
        label : str
            Display label (e.g., "FFT").
        key : str
            Key used in health_indicators dict for updates.
        """
        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        text = QtWidgets.QLabel(label)
        indicator = QtWidgets.QLabel()
        indicator.setFixedSize(12, 12)
        indicator.setStyleSheet(self._indicator_style("#cc0000"))
        layout.addWidget(text)
        layout.addWidget(indicator)
        container.setLayout(layout)
        self.health_indicators[key] = indicator
        return container

    def _update_health_indicator(self, key: str, level: str) -> None:
        """Update a health indicator color from a level string."""
        if not self.health_indicators or key not in self.health_indicators:
            return
        if level == "green":
            color = "#00aa00"
        elif level == "yellow":
            color = "#c8a800"
        else:
            color = "#cc0000"
        self.health_indicators[key].setStyleSheet(self._indicator_style(color))

    def _on_connect_clicked(self) -> None:
        """
        Handle Connect/Disconnect button: disconnect, or validate IP and connect.

        If already connected, disconnects and refreshes UI. Otherwise validates
        IP, creates RPConnection, connects, optionally reads one frame,
        set_connection, saves IP to QSettings, updates window title. On failure
        disconnects and shows error in title.

        Returns
        -------
        None
        """
        if self._layout is None:
            return
        if self._layout.is_connected():
            self._layout.disconnect()
            self._refresh_connection_ui()
            self._set_window_title(" - disconnected")
            return

        ip = (self.ip_input.text() if self.ip_input is not None else "").strip()
        if not _is_valid_host(ip):
            # Keep disconnected; indicator stays red.
            self._refresh_connection_ui()
            return

        try:
            connection = acq.RPConnection()
            connection.connect(ip, 1001, timeout_s=0.5)
            # Push config before first frame read. On reconnect, discard initial
            # frames to flush transitional/corrupted data, then use a valid frame.
            self._layout.set_connection(connection)
            session = self._layout.session
            if connection.capability_line is None:
                session.log_warning("Capability handshake: none (defaulting to laser_lock until inferred).")
            else:
                session.log_warning(
                    f"Capability handshake: {connection.capability_line} (variant={connection.server_variant})."
                )
            time.sleep(0.2)  # let server process config and build valid frames
            for _ in range(3):  # discard up to 3 frames to resync stream
                _ = connection.read_frame(
                    timeout_s=0.3, suppress_corruption_warning=True
                )
            data0 = None
            for _ in range(5):  # retry up to 5 times to get a valid frame
                data0 = connection.read_frame(
                    timeout_s=0.5, suppress_corruption_warning=True
                )
                if data0 is not None:
                    break
            if data0 is not None:
                self._layout.dataset.substitute_data(data0)
            if data0 is not None:
                session = self._layout.session
                session.dataset.update_t()
                eff0, _ = aux.effective_beatfreq(
                    session.dataset.spectrum[0], session.dataset.beatfreq[0],
                    session.dataset.f
                )
                eff1, _ = aux.effective_beatfreq(
                    session.dataset.spectrum[1], session.dataset.beatfreq[1],
                    session.dataset.f
                )
                session.dataset.beatfreq[0] = eff0
                session.dataset.beatfreq[1] = eff1
                session.widgets.beatfreq = session.dataset.beatfreq.copy()
                cap_line = connection.capability_line
                inferred_phasemeter = aux.infer_phasemeter_from_snapshot(session.dataset)
                if cap_line is None:
                    if inferred_phasemeter and connection.server_variant != rp_protocol.RP_CAP_PHASEMETER:
                        connection.set_server_variant(rp_protocol.RP_CAP_PHASEMETER)
                        self._layout.apply_server_variant()
                        session.log_warning(
                            "Capability handshake missing; inferred phasemeter mode from frame data."
                        )
                    elif not inferred_phasemeter:
                        session.log_warning(
                            "Capability handshake missing; defaulting to laser lock mode."
                        )
                elif not cap_line.startswith(rp_protocol.RP_CAP_PREFIX):
                    session.log_warning(
                        f"Unexpected capability line: {cap_line!r}. Defaulting to laser lock mode."
                    )
                elif connection.server_variant == rp_protocol.RP_CAP_LASER_LOCK and inferred_phasemeter:
                    session.log_warning(
                        "Capability handshake reports laser_lock, but frame data looks like phasemeter."
                    )
                plot_vm = session.build_plot_view_model()
                if not session.render_paused:
                    session.gui.updateGUIs(plot_vm)

            settings = QtCore.QSettings("rpll", "gui")
            settings.setValue(self._ip_settings_key, ip)

            self._refresh_connection_ui()
            self._set_window_title(f" - connected to {ip}")
        except Exception:
            self._layout.disconnect()
            self._refresh_connection_ui()
            self._set_window_title(f" - disconnected (connect failed: {ip})")

    def connect_to_host(self, host: str) -> bool:
        """Set host field and attempt to connect. Returns True if connected."""
        if self.ip_input is not None:
            self.ip_input.setText(host)
        self._on_connect_clicked()
        return bool(self._layout and self._layout.is_connected())

    def disconnect(self) -> None:
        """Disconnect if connected and refresh UI."""
        if self._layout is None:
            return
        if self._layout.is_connected():
            self._layout.disconnect()
        self._refresh_connection_ui()
        self._set_window_title(" - disconnected")

    def is_connected(self) -> bool:
        """Return True when the layout reports an active connection."""
        return bool(self._layout and self._layout.is_connected())

    def update_top_bar_stats(self) -> None:
        """
        Update Frames, FPS, Parse errors labels from layout and refresh connection UI.

        Reads frame_count, fps, parse_error_count from layout and updates
        the top bar labels; also refreshes connection indicator.

        Returns
        -------
        None
        """
        if self._layout is None:
            return
        if self.frames_label is not None:
            self.frames_label.setText(f"Frames: {self._layout.frame_count}")
        if self.fps_label is not None:
            self.fps_label.setText(f"FPS: {self._layout.fps:.1f}")
        if self.parse_errors_label is not None:
            self.parse_errors_label.setText(f"Parse errors: {self._layout.parse_error_count}")
        if self.health_indicator_widgets is not None and self._layout is not None:
            if self._layout.is_connected():
                self._last_phasemeter_mode = self._layout.is_phasemeter_mode()
            is_phasemeter = self._last_phasemeter_mode
            for key in ("freq_error", "ctrl"):
                widget = self.health_indicator_widgets.get(key)
                if widget is not None:
                    widget.setVisible(not is_phasemeter)
        if self.health_indicators is not None:
            if not self._layout.is_connected():
                for key in self.health_indicators.keys():
                    self._update_health_indicator(key, "red")
            else:
                health = aux.compute_health_snapshot(
                    self._layout.dataset, self._layout.is_phasemeter_mode()
                )
                self._update_health_indicator("fft", health.fft)
                self._update_health_indicator("i_value", health.i_value)
                self._update_health_indicator("q_value", health.q_value)
                self._update_health_indicator("freq_readout", health.freq_readout)
                self._update_health_indicator("freq_error", health.freq_error)
                self._update_health_indicator("ctrl", health.ctrl)
        # Connection can drop asynchronously (EOF); reflect it here.
        self._refresh_connection_ui()


class ConnectDialog(QtWidgets.QDialog):
    """Dialog to enter RedPitaya host/IP and connect."""

    def __init__(self, parent=None, default_host: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Connect to RedPitaya")

        self._host_input = QtWidgets.QLineEdit(default_host)
        self._host_input.setPlaceholderText("IP address or hostname")

        form = QtWidgets.QFormLayout()
        form.addRow("Host:", self._host_input)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def host(self) -> str:
        return self._host_input.text().strip()

    def accept(self) -> None:
        host = self.host()
        if not _is_valid_host(host):
            QtWidgets.QMessageBox.warning(self, "Invalid host", "Enter a valid IP or hostname.")
            return
        super().accept()


class DataLoggingDialog(QtWidgets.QDialog):
    """Dialog for data logging setup (path, channels, duration)."""

    def __init__(self, parent=None, default_path: str = "", default_channels: Iterable[int] = (0, 1)):
        super().__init__(parent)
        self.setWindowTitle("Start Data Logging")

        self._path_input = QtWidgets.QLineEdit(default_path)
        browse_btn = QtWidgets.QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_path)

        path_layout = QtWidgets.QHBoxLayout()
        path_layout.addWidget(self._path_input, 1)
        path_layout.addWidget(browse_btn)

        self._ch1_cb = QtWidgets.QCheckBox("Channel 1")
        self._ch2_cb = QtWidgets.QCheckBox("Channel 2")
        self._ch1_cb.setChecked(0 in default_channels)
        self._ch2_cb.setChecked(1 in default_channels)

        channels_layout = QtWidgets.QHBoxLayout()
        channels_layout.addWidget(self._ch1_cb)
        channels_layout.addWidget(self._ch2_cb)
        channels_layout.addStretch(1)

        self._until_stopped = QtWidgets.QRadioButton("Until stopped")
        self._stop_after = QtWidgets.QRadioButton("Stop after (s)")
        self._duration_spin = QtWidgets.QSpinBox()
        self._duration_spin.setRange(1, 3600 * 24 * 365 * 30)
        self._duration_spin.setEnabled(False)
        self._until_stopped.setChecked(True)
        self._stop_after.toggled.connect(self._duration_spin.setEnabled)

        duration_layout = QtWidgets.QHBoxLayout()
        duration_layout.addWidget(self._until_stopped)
        duration_layout.addWidget(self._stop_after)
        duration_layout.addWidget(self._duration_spin)
        duration_layout.addStretch(1)

        form = QtWidgets.QFormLayout()
        form.addRow("File path:", path_layout)
        form.addRow("Channels:", channels_layout)
        form.addRow("Duration:", duration_layout)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def _browse_path(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Select data file",
            self._path_input.text(),
            "Text Files (*.txt);;All Files (*)",
        )
        if path:
            self._path_input.setText(path)

    def output_path(self) -> str:
        return self._path_input.text().strip()

    def selected_channels(self) -> tuple:
        channels = []
        if self._ch1_cb.isChecked():
            channels.append(0)
        if self._ch2_cb.isChecked():
            channels.append(1)
        return tuple(channels)

    def duration_seconds(self) -> Optional[int]:
        if self._stop_after.isChecked():
            return int(self._duration_spin.value())
        return None

    def accept(self) -> None:
        if not self.output_path():
            QtWidgets.QMessageBox.warning(self, "Missing path", "Choose a file path.")
            return
        if not self.selected_channels():
            QtWidgets.QMessageBox.warning(self, "Missing channels", "Select at least one channel.")
            return
        super().accept()


class ExportPlotsDialog(QtWidgets.QDialog):
    """Dialog for exporting plots (plot, channels, filename, format)."""

    def __init__(
        self,
        parent=None,
        plot_options=None,
        default_format: str = "png",
        default_path: str = "",
        default_channels: Iterable[int] = (0, 1),
    ):
        super().__init__(parent)
        self.setWindowTitle("Export Plots")

        self._plot_combo = QtWidgets.QComboBox()
        plot_options = plot_options or []
        for label, key in plot_options:
            self._plot_combo.addItem(label, key)

        self._format_combo = QtWidgets.QComboBox()
        self._format_combo.addItem("PNG", "png")
        self._format_combo.addItem("SVG", "svg")
        self._format_combo.addItem("PDF", "pdf")
        for idx in range(self._format_combo.count()):
            if self._format_combo.itemData(idx) == default_format:
                self._format_combo.setCurrentIndex(idx)
                break

        self._path_input = QtWidgets.QLineEdit(default_path)
        browse_btn = QtWidgets.QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_path)

        path_layout = QtWidgets.QHBoxLayout()
        path_layout.addWidget(self._path_input, 1)
        path_layout.addWidget(browse_btn)

        self._ch1_cb = QtWidgets.QCheckBox("Channel 1")
        self._ch2_cb = QtWidgets.QCheckBox("Channel 2")
        self._ch1_cb.setChecked(0 in default_channels)
        self._ch2_cb.setChecked(1 in default_channels)

        channels_layout = QtWidgets.QHBoxLayout()
        channels_layout.addWidget(self._ch1_cb)
        channels_layout.addWidget(self._ch2_cb)
        channels_layout.addStretch(1)

        form = QtWidgets.QFormLayout()
        form.addRow("Plot:", self._plot_combo)
        form.addRow("Channels:", channels_layout)
        form.addRow("Filename:", path_layout)
        form.addRow("Format:", self._format_combo)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def _browse_path(self) -> None:
        fmt = self.selected_format()
        filt = {
            "png": "PNG Image (*.png)",
            "svg": "SVG (*.svg)",
            "pdf": "PDF (*.pdf)",
        }.get(fmt, "All Files (*)")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export plot",
            self._path_input.text(),
            f"{filt};;All Files (*)",
        )
        if path:
            self._path_input.setText(path)

    def selected_plot_key(self) -> str:
        return self._plot_combo.currentData()

    def selected_channels(self) -> tuple:
        channels = []
        if self._ch1_cb.isChecked():
            channels.append(0)
        if self._ch2_cb.isChecked():
            channels.append(1)
        return tuple(channels)

    def selected_path(self) -> str:
        return self._path_input.text().strip()

    def selected_format(self) -> str:
        return self._format_combo.currentData()

    def accept(self) -> None:
        if not self.selected_path():
            QtWidgets.QMessageBox.warning(self, "Missing filename", "Choose an output filename.")
            return
        if not self.selected_channels():
            QtWidgets.QMessageBox.warning(self, "Missing channels", "Select at least one channel.")
            return
        super().accept()


class MainWindow(QtWidgets.QMainWindow):
    """
    Behavioral spec (pre-menu): connection toggles from the top bar; data dumps
    are started/stopped via the data logger button; plots render each tick.

    Design note: the menu centralizes these actions and their enabled/checked
    state to reduce direct UI coupling.
    """

    def __init__(self, session: ly.Session, layout: ly.MainLayout, default_ip: str):
        super().__init__()
        self._session = session
        self._layout = layout
        self._settings = QtCore.QSettings("rpll", "gui")
        self._actions = {}

        self._central = MainWidget()
        self._central.registerLayout(layout, default_ip=default_ip)
        self.setCentralWidget(self._central)

        self._plot_options = [
            ("Spectrum", "spectrum"),
            ("I(t)", "i_value"),
            ("Q(t)", "q_value"),
            ("Frequency Readout", "frequency"),
        ]
        self._build_menu_bar()
        self._central._set_window_title(" - disconnected")
        self.refresh_menu_state()
        QtCore.QTimer.singleShot(0, self._layout.capture_default_layout)

    def _log_status(self, msg: str) -> None:
        self._session.log_warning(msg)

    def _build_menu_bar(self) -> None:
        menu_bar = self.menuBar()

        rp_menu = menu_bar.addMenu("RedPitaya")
        connect_action = rp_menu.addAction("Connect…")
        disconnect_action = rp_menu.addAction("Disconnect")
        reacquire_action = rp_menu.addAction("Reacquire")
        copy_settings_action = rp_menu.addAction("Copy Channel 1 Settings to Channel 2")
        rp_menu.addSeparator()
        quit_action = rp_menu.addAction("Quit")
        quit_action.setShortcut(QtGui.QKeySequence.Quit)

        connect_action.triggered.connect(self._connect_dialog)
        disconnect_action.triggered.connect(self._disconnect)
        reacquire_action.triggered.connect(self._reacquire)
        copy_settings_action.triggered.connect(self._copy_settings)
        quit_action.triggered.connect(self._quit_app)

        file_menu = menu_bar.addMenu("File")
        start_dump_action = file_menu.addAction("Start Data Logging…")
        stop_dump_action = file_menu.addAction("Stop Data Logging")
        file_menu.addSeparator()
        export_action = file_menu.addAction("Export Plots…")

        start_dump_action.triggered.connect(self._start_data_logging_dialog)
        stop_dump_action.triggered.connect(self._stop_data_logging)
        export_action.triggered.connect(self._export_plots_dialog)

        view_menu = menu_bar.addMenu("View")
        left_panel_action = view_menu.addAction("Show/Hide Left Control Panel")
        left_panel_action.setCheckable(True)
        warnings_action = view_menu.addAction("Show/Hide Warnings Log")
        warnings_action.setCheckable(True)
        view_menu.addSeparator()
        panels_menu = view_menu.addMenu("Show/Hide Panels")

        panel_actions = {}
        for label, key in self._plot_options:
            action = panels_menu.addAction(label)
            action.setCheckable(True)
            action.toggled.connect(lambda checked, k=key: self._toggle_plot_panel(k, checked))
            panel_actions[key] = action

        view_menu.addSeparator()
        reset_layout_action = view_menu.addAction("Reset Layout")
        autoscale_action = view_menu.addAction("Autoscale Y (per plot)")
        autoscale_action.setCheckable(True)
        pause_action = view_menu.addAction("Pause Rendering")
        pause_action.setCheckable(True)
        view_menu.addSeparator()
        fullscreen_action = view_menu.addAction("Full Screen")
        fullscreen_action.setCheckable(True)
        fullscreen_action.setShortcut(QtGui.QKeySequence.FullScreen)

        left_panel_action.toggled.connect(self._toggle_left_panel)
        warnings_action.toggled.connect(self._toggle_warnings)
        reset_layout_action.triggered.connect(self._reset_layout)
        autoscale_action.toggled.connect(self._toggle_autoscale_y)
        pause_action.toggled.connect(self._toggle_pause_rendering)
        fullscreen_action.toggled.connect(self._toggle_full_screen)

        self._actions.update(
            {
                "connect": connect_action,
                "disconnect": disconnect_action,
                "reacquire": reacquire_action,
                "copy_settings": copy_settings_action,
                "quit": quit_action,
                "start_dump": start_dump_action,
                "stop_dump": stop_dump_action,
                "export": export_action,
                "toggle_left": left_panel_action,
                "toggle_warnings": warnings_action,
                "reset_layout": reset_layout_action,
                "autoscale_y": autoscale_action,
                "pause_rendering": pause_action,
                "full_screen": fullscreen_action,
                "panel_actions": panel_actions,
            }
        )

    def refresh_menu_state(self) -> None:
        connected = self._layout.is_connected()
        self._actions["connect"].setEnabled(not connected)
        self._actions["disconnect"].setEnabled(connected)
        self._actions["reacquire"].setEnabled(connected)
        self._actions["copy_settings"].setEnabled(connected)

        dumping = bool(self._layout.widgets.data_write_flag)
        self._actions["start_dump"].setEnabled(not dumping)
        self._actions["stop_dump"].setEnabled(dumping)

        self._actions["toggle_left"].setChecked(self._layout.controls_widget.isVisible())
        self._actions["toggle_warnings"].setChecked(self._layout.warnings_group.isVisible())

        for key, action in self._actions["panel_actions"].items():
            action.setChecked(self._layout.is_plot_visible(key))

        active_plot = self._session.gui.get_active_plot_key()
        self._actions["autoscale_y"].setChecked(self._session.gui.is_plot_autoscale_y(active_plot))
        self._actions["pause_rendering"].setChecked(self._layout.is_render_paused())
        self._actions["full_screen"].setChecked(self.isFullScreen())

    def update_runtime_ui(self) -> None:
        self._central.update_top_bar_stats()
        self.refresh_menu_state()

    def _connect_dialog(self) -> None:
        default_host = self._central.ip_input.text().strip() if self._central.ip_input else ""
        dialog = ConnectDialog(self, default_host=default_host)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            host = dialog.host()
            self._log_status(f"Connecting to {host}...")
            connected = self._central.connect_to_host(host)
            if connected:
                self._log_status(f"Connected to {host}.")
            else:
                self._log_status(f"Connect failed: {host}.")
            self.refresh_menu_state()

    def _disconnect(self) -> None:
        if self._layout.is_connected():
            self._log_status("Disconnecting...")
        self._central.disconnect()
        self.refresh_menu_state()

    def _reacquire(self) -> None:
        if not self._layout.is_connected():
            return
        self._log_status("Reacquire triggered.")
        self._layout.reacquire()

    def _copy_settings(self) -> None:
        if not self._layout.is_connected():
            return
        self._layout.widgets.copy_settings_to_channel_2()
        self._log_status("Copied channel 1 settings to channel 2.")

    def _default_data_log_path(self) -> str:
        now = QtCore.QDateTime.currentDateTime().toString("yyyy_MM_dd_HH_mm_ss")
        repo_root = Path(__file__).resolve().parent.parent
        return str(repo_root / "readout" / now / f"{now}_data.txt")

    def _start_data_logging_dialog(self) -> None:
        default_path = self._settings.value("data_log_path", self._default_data_log_path(), type=str)
        dialog = DataLoggingDialog(self, default_path=default_path)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            output_path = dialog.output_path()
            channels = dialog.selected_channels()
            duration_s = dialog.duration_seconds()
            started = self._layout.widgets.start_datadump(
                output_path=output_path,
                channels=channels,
                duration_s=duration_s,
            )
            self._settings.setValue("data_log_path", output_path)
            if started:
                self._log_status(f"Data logging started: {output_path}")
            else:
                self._log_status("Data logging already running.")
            self.refresh_menu_state()

    def _stop_data_logging(self) -> None:
        stopped = self._layout.widgets.stop_datadump()
        if stopped:
            self._log_status("Data logging stopped.")
        self.refresh_menu_state()

    def _export_plots_dialog(self) -> None:
        default_format = self._settings.value("export_plot_format", "png", type=str)
        default_path = self._settings.value("export_plot_path", "", type=str)
        dialog = ExportPlotsDialog(
            self,
            plot_options=self._plot_options,
            default_format=default_format,
            default_path=default_path,
        )
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            plot_key = dialog.selected_plot_key()
            channels = dialog.selected_channels()
            fmt = dialog.selected_format()
            path = self._normalize_export_path(dialog.selected_path(), fmt)
            self._settings.setValue("export_plot_format", fmt)
            self._settings.setValue("export_plot_path", path)
            self._export_plot(plot_key, channels, fmt, path)

    def _normalize_export_path(self, path: str, fmt: str) -> str:
        if not path:
            return path
        suffix = f".{fmt}"
        lower = path.lower()
        for ext in (".png", ".svg", ".pdf"):
            if lower.endswith(ext):
                base = path[:-len(ext)]
                return base + suffix
        if not lower.endswith(suffix):
            return path + suffix
        return path

    def _export_plot(self, plot_key: str, channels: Iterable[int], fmt: str, path: str) -> None:
        plot = self._session.gui.get_plot_widget(plot_key)
        if plot is None:
            self._log_status("Export failed: plot not found.")
            return

        self._log_status(f"Exporting {plot_key} plot to {path}...")
        channel_set = set(channels)
        items_by_channel = self._session.gui.get_plot_channel_items(plot_key)
        hidden = []
        for ch, items in items_by_channel.items():
            if ch not in channel_set:
                for item in items:
                    hidden.append((item, item.isVisible()))
                    item.setVisible(False)
        try:
            QtWidgets.QApplication.processEvents()
            import pyqtgraph.exporters as pg_exporters
            if fmt == "png":
                exporter = pg_exporters.ImageExporter(plot.getPlotItem())
            elif fmt == "svg":
                exporter = pg_exporters.SVGExporter(plot.getPlotItem())
            elif fmt == "pdf":
                exporter = pg_exporters.PDFExporter(plot.getPlotItem())
            else:
                exporter = pg_exporters.ImageExporter(plot.getPlotItem())
            exporter.export(path)
            self._log_status(f"Export complete: {path}")
        except Exception as exc:
            self._log_status(f"Export failed: {exc}")
        finally:
            for item, was_visible in hidden:
                item.setVisible(was_visible)

    def _toggle_left_panel(self, visible: bool) -> None:
        self._layout.set_controls_visible(visible)
        self.refresh_menu_state()

    def _toggle_warnings(self, visible: bool) -> None:
        self._layout.set_warnings_visible(visible)
        self.refresh_menu_state()

    def _toggle_plot_panel(self, key: str, visible: bool) -> None:
        self._layout.set_plot_visible(key, visible)
        self.refresh_menu_state()

    def _reset_layout(self) -> None:
        self._layout.reset_layout()
        self.refresh_menu_state()

    def _toggle_autoscale_y(self, enabled: bool) -> None:
        plot_key = self._session.gui.get_active_plot_key()
        self._session.gui.set_plot_autoscale_y(plot_key, enabled)
        self.refresh_menu_state()

    def _toggle_pause_rendering(self, paused: bool) -> None:
        self._layout.set_render_paused(paused)
        self.refresh_menu_state()

    def _toggle_full_screen(self, enabled: bool) -> None:
        if enabled:
            self.showFullScreen()
        else:
            self.showNormal()
        self.refresh_menu_state()

    def _quit_app(self) -> None:
        self.close()

    def closeEvent(self, event) -> None:
        if self._layout.widgets.data_write_flag:
            self._layout.widgets.stop_datadump()
        if self._layout.is_connected():
            self._layout.disconnect()
        self.refresh_menu_state()
        super().closeEvent(event)

def main(argv=None):
    """
    Entry point: parse args, create app, session, layout, main widget; run event loop.

    Parameters
    ----------
    argv : list of str or None, optional
        Command-line arguments. If None, uses sys.argv. Default is None.

    Returns
    -------
    int
        0 on normal exit. Saves widget config to config.json on exit.
    """
    from argparse import ArgumentParser
    parser = ArgumentParser()
    parser.add_argument("--ip", "-H", dest="ip", default="10.128.100.11")
    args, argv_rest = parser.parse_known_args(argv)

    # === initialize GUI (do not block on RP connection) =============
    app = QtWidgets.QApplication(sys.argv[:1] + argv_rest)
    session = ly.Session()
    layout = ly.MainLayout(session)
    window = MainWindow(session, layout, default_ip=str(args.ip))
    window.show()

    # === real-time processing =============
    timer = QtCore.QTimer()
    def tick():
        session.process_tick()
        window.update_runtime_ui()
    timer.timeout.connect(tick)
    timer.start(int(glp.dt * 1e3))
    timer_auto_stop = QtCore.QTimer()
    timer_auto_stop.timeout.connect(session.widgets.datadump_timer)
    timer_auto_stop.start(1000)

    # Qt5 used exec_(); Qt6 uses exec().
    getattr(app, "exec", app.exec_)()
    session.widgets.setFinalValues(os.path.join(os.path.dirname(__file__), 'config.json'))

    return 0


if __name__ == '__main__':
    raise SystemExit(main())


