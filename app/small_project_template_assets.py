from pathlib import Path
import base64

TEMPLATES = (
    "MEP_Template_SmallProject_2026_08.docx",
    "CIP_Template_SmallProject_2026_07.docx",
)


def materialize_small_project_template_assets() -> None:
    root = Path(__file__).parent / "small_project_templates"
    root.mkdir(parents=True, exist_ok=True)
    for filename in TEMPLATES:
        target = root / filename
        if target.exists():
            continue
        parts = sorted(root.glob(filename + ".b64.part*"))
        if not parts:
            continue
        encoded = "".join(part.read_text(encoding="utf-8").strip() for part in parts)
        if encoded:
            target.write_bytes(base64.b64decode(encoded))
