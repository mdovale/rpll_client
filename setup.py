from setuptools import setup


setup(
    name="rp-ll-gui",
    version="0.1.0",
    description="GUI client for rpll RedPitaya laser offset locking",
    py_modules=[
        "acquire",
        "data_models",
        "frame_schema",
        "global_params",
        "gui",
        "layout",
        "main",
        "rp_protocol",
        "widgets",
    ],
    install_requires=[
        "numpy",
        # pyqtgraph needs a Qt binding at runtime; pick a default.
        "PySide6",
        "pyqtgraph",
    ],
    extras_require={
        # Dev dependencies: run tests with pip install -e ".[dev]" then pytest tests
        "dev": ["pytest"],
    },
    entry_points={
        "console_scripts": [
            "rpll-client=main:main",
        ],
    },
    python_requires=">=3.8",
)
