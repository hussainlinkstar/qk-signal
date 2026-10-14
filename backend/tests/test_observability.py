from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from observability import status_class_from_code


def test_status_class_from_code_maps_ranges() -> None:
    assert status_class_from_code(200) == "2xx"
    assert status_class_from_code(302) == "3xx"
    assert status_class_from_code(404) == "4xx"
    assert status_class_from_code(500) == "5xx"
