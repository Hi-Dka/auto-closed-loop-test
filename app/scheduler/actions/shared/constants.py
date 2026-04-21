"""Reusable constants for scan action validation and dispatch."""

DEFAULT_ENDPOINT = "http://127.0.0.1:8000"

SERVICE_LIST = [
    {"label": "music srv one", "id": 0x4DAA},
    {"label": "music srv two", "id": 0x4DAB},
]

SELECT_LIST = [
    {"service_id": 0x4DAA, "component_id": 2, "frequency": 227360000},
    {"service_id": 0x4DAB, "component_id": 3, "frequency": 227360000},
]

ENSEMBLE_ID = 0x4FFE
ENSEMBLE_LABEL = "OpenDigitalRadio"
ENSEMBLE_SERVICES = SERVICE_LIST
