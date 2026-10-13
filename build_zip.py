"""Build the installable BlendCap Motion Bridge zip."""

import os
from pathlib import Path
import zipfile


DEV = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(DEV, "blendcap_motion_bridge")
PACKAGE_FILES = (
    "__init__.py",
    "blender_manifest.toml",
    "face_mapper.py",
    "mmd_mapper.py",
    "operators.py",
    "panels.py",
    "preset_writer.py",
)


def _version():
    manifest = os.path.join(PKG, "blender_manifest.toml")
    with open(manifest, encoding="utf-8") as f:
        for line in f:
            if line.startswith("version ="):
                return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("version missing from blender_manifest.toml")


def main():
    workspace = next((p for p in Path(DEV).parents if (p / "Agent Delivery").is_dir() and (p / "Agent Tools").is_dir()), None)
    delivery = workspace / "Agent Delivery" / "Motion_Bridge" if workspace else Path(DEV)
    delivery.mkdir(parents=True, exist_ok=True)
    archive_name = f"BlendCap-{_version()}.zip" if workspace else f"blendcap_motion_bridge-{_version()}.zip"
    out = str(delivery / archive_name)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in PACKAGE_FILES:
            zf.write(
                os.path.join(PKG, name),
                arcname=os.path.join("blendcap_motion_bridge", name),
            )
    print("ZIP_OK", out)


if __name__ == "__main__":
    main()
