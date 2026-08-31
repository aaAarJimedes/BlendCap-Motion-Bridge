"""Factory-startup registration and single-panel smoke for version 0.3.0."""

import importlib
from pathlib import Path
import sys
from types import SimpleNamespace

import bpy


if not bpy.app.background:
    raise RuntimeError("background-only test")

sys.path.insert(0, str(Path(__file__).parent))
addon = importlib.import_module("blendcap_motion_bridge")
addon.register()

required = (
    "blendcap_motion_bridge.auto_select",
    "blendcap_motion_bridge.detect",
    "blendcap_motion_bridge.prepare_in_memory",
    "blendcap_motion_bridge.quick_retarget",
    "blendcap_motion_bridge.apply_face",
    "blendcap_motion_bridge.disable_leg_overrides",
    "blendcap_motion_bridge.restore_leg_overrides",
    "blendcap_motion_bridge.relink_leg_deform",
    "blendcap_motion_bridge.restore_previous_state",
)
for path in required:
    namespace, name = path.split(".", 1)
    getattr(getattr(bpy.ops, namespace), name).get_rna_type()

for name in (
    "blendcap_motion_bridge_status",
    "blendcap_motion_bridge_mapping_signature",
    "blendcap_motion_bridge_constraint_snapshot",
    "blendcap_motion_bridge_previous_table_json",
):
    assert hasattr(bpy.types.Scene, name), name

assert addon.bl_info["name"] == "BlendCap Motion Bridge"
assert addon.bl_info["version"] == (0, 3, 0)
assert addon.panels.CLASSES == (addon.panels.BCMB_PT_main,)
assert addon.panels.BCMB_PT_main.bl_label == "BlendCap Motion Bridge"


class RecordingLayout:
    def __init__(self):
        self.labels = []
        self.operators = []
        self.alert = False
        self.enabled = True
        self.scale_y = 1.0
        self.use_property_split = False
        self.use_property_decorate = True

    def box(self):
        return self

    def row(self, **_kwargs):
        return self

    def column(self, **_kwargs):
        return self

    def label(self, text="", **_kwargs):
        self.labels.append(text)

    def operator(self, operator_id, **_kwargs):
        self.operators.append(operator_id)
        return SimpleNamespace()

    def prop(self, *_args, **_kwargs):
        return None

    def prop_search(self, *_args, **_kwargs):
        return None

    def separator(self):
        return None


bpy.types.Scene.blendcap_retarget_source = bpy.props.PointerProperty(type=bpy.types.Object)
bpy.types.Scene.blendcap_retarget_target = bpy.props.PointerProperty(type=bpy.types.Object)
bpy.context.scene.blendcap_motion_bridge_previous_state_available = True
layout = RecordingLayout()
addon.panels.BCMB_PT_main.draw(SimpleNamespace(layout=layout), bpy.context)
expected_sections = (
    "1 · 动作来源与角色",
    "2 · 动作重定向",
    "3 · MMD 表情",
    "4 · VMD 与烘焙后处理",
)
positions = [layout.labels.index(label) for label in expected_sections]
assert positions == sorted(positions), positions
for operator_id in required:
    assert layout.operators.count(operator_id) == 1, operator_id
del bpy.types.Scene.blendcap_retarget_source
del bpy.types.Scene.blendcap_retarget_target
bpy.context.scene.blendcap_motion_bridge_previous_state_available = False

addon.unregister()
print("BLENDCAP_MOTION_BRIDGE_REGISTRATION_030=PASS")
