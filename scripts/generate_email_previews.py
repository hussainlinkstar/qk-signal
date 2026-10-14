import sys
import os
from pathlib import Path

# Add backend dir to python path
backend_path = Path(__file__).parent.parent / "backend"
if not backend_path.exists():
    # Running inside Docker container where /app is the backend
    backend_path = Path("/app")
sys.path.insert(0, str(backend_path))

# Ensure environmental variables won't disrupt standalone loading
os.environ["APP_ENV"] = "test"

from services.email_templates import DEFAULT_PREVIEW_CONTEXT, TEMPLATE_DEFINITIONS, render_template

dummy_context = DEFAULT_PREVIEW_CONTEXT

output_dir = backend_path / "email_previews"
output_dir.mkdir(exist_ok=True)

success_count = 0
for key, definition in TEMPLATE_DEFINITIONS.items():
    try:
        rendered = render_template(key, dummy_context)
        file_path = output_dir / f"{definition.html_template}"
        file_path.write_text(rendered.html, encoding="utf-8")
        print(f"Generated {file_path.name} (Key: {key})")
        success_count += 1
    except Exception as e:
        print(f"Failed to generate {definition.html_template} (Key: {key}): {e}")

print(f"\nSuccessfully generated {success_count} templates in {output_dir.absolute()}")
