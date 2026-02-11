# Client tests

Run tests from the **rpll_client** folder with the venv activated:

```bash
cd rpll_client
source .venv/bin/activate
pip install -e ".[dev]"   # install package + pytest
PYTHONPATH=. python -m pytest tests -v
```

Or install pytest only: `pip install pytest`.

Tests cover:
- **frame_schema**: constants (must match server memory_map.h)
- **data_models**: DataPackage.parse_frame, build_plot_view_model, effective_beatfreq, substitute_data, clear
- **rp_protocol**: encoding (pack_register_write, pack_reset, etc.)
- **acquire**: check_frame_corruption, RPConnection (no socket)

No Qt or network required.
