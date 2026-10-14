"""Qiko mark packaged with the PDF worker."""

import base64
from pathlib import Path

# The Qiko mark alone (no wordmark), matching frontend/public/qiko-logo.png.
# The approved cover lockup sets the "Signal" word in Satoshi beside it; the
# reportlab running header carries the mark alone.
_QIKO_MARK = Path(__file__).resolve().parent / "assets" / "qiko-logo.png"
QIKO_MARK_DATA_URI = "data:image/png;base64," + base64.b64encode(_QIKO_MARK.read_bytes()).decode(
    "ascii"
)
