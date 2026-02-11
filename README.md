# rpll client

Python GUI client for the rpll RedPitaya laser offset locking system. It connects to the RedPitaya server over TCP and provides a real-time interface for monitoring and control.

## Requirements

- Python ≥ 3.8
- RedPitaya board running the rpll server (see project root [README](../README.md))

## Install

From the repo root or from this directory:

```bash
pip install -e .
```

This installs the package `rp-ll-gui` and its dependencies: `numpy`, `PySide6`, `pyqtgraph`.

Optional (for running tests):

```bash
pip install -e ".[dev]"
```

## Run

With default IP (from `global_params`):

```bash
python main.py
```

Or specify the RedPitaya IP:

```bash
python main.py -H 10.0.0.2
```

If installed via pip, you can also run:

```bash
rp-ll-gui -H 10.0.0.2
```

The GUI connects to the server on port 1001. Use the top bar to enter the IP and click **Connect**. The last used IP is stored and restored on next start.

## Tests

From the `client` directory, with the package installed (including `[dev]` for pytest):

```bash
PYTHONPATH=. python -m pytest tests -v
```

Tests cover frame schema constants, `DataPackage` parsing and plot view model, and `rp_protocol` encoding. No Qt or network is required.

See [tests/README.md](tests/README.md) for more detail.

## Module overview

| Module          | Role |
|-----------------|------|
| `main.py`       | Entry point; `MainWidget`, top bar (IP, Connect, status, FPS), timer loop. |
| `acquire.py`    | `RPConnection`: TCP socket, RX buffer, frame reading. |
| `rp_protocol.py`| Encodes register writes and reset commands for the server. |
| `frame_schema.py` | Frame layout constants (sizes, offsets) used by acquire and data_models. |
| `data_models.py`  | `DataPackage`, parsing of binary frames, plot view model. |
| `layout.py`       | `Session`, `MainLayout`; connection lifecycle and main splitter. |
| `gui.py`          | GUI helpers and wiring. |
| `widgets.py`      | Plot and control widgets. |
| `global_params.py`| Timing and default IP. |

Configuration (e.g. window layout) is saved on exit to `config.json` in this directory.
