"""BlendCap Motion Bridge: map BlendCap BVH motion onto MMD characters.

The add-on reads the two rigs selected in BlendCap's Retargeting panel,
matches BlendCap's BVH source bones onto common MMD Tools bone names, and
generates a BlendCap preset JSON that is loaded into the pair table.
"""

bl_info = {
    "name": "BlendCap Motion Bridge",
    "author": "aaAarJimedes",
    "version": (0, 3, 0),
    "blender": (4, 2, 0),
    "location": "3D Viewport > Sidebar > BlendCap",
    "description": "Bridge BlendCap BVH motion and facial capture to MMD characters",
    "category": "Animation",
}

import bpy

from . import operators
from . import panels


def register():
    bpy.types.Scene.blendcap_motion_bridge_matched = bpy.props.IntProperty(
        name="Matched", default=0
    )
    bpy.types.Scene.blendcap_motion_bridge_total = bpy.props.IntProperty(
        name="Total", default=0
    )
    bpy.types.Scene.blendcap_motion_bridge_unmatched = bpy.props.StringProperty(
        name="Unmatched", default=""
    )
    bpy.types.Scene.blendcap_motion_bridge_last_preset = bpy.props.StringProperty(
        name="Last Preset", default=""
    )
    bpy.types.Scene.blendcap_motion_bridge_face_npz = bpy.props.StringProperty(
        name="Face NPZ", subtype="FILE_PATH", default=""
    )
    bpy.types.Scene.blendcap_motion_bridge_face_mesh = bpy.props.PointerProperty(
        name="Face Mesh", type=bpy.types.Object
    )
    bpy.types.Scene.blendcap_motion_bridge_face_matched = bpy.props.IntProperty(
        name="Face Matched", default=0
    )
    bpy.types.Scene.blendcap_motion_bridge_face_total = bpy.props.IntProperty(
        name="Face Total", default=0
    )
    bpy.types.Scene.blendcap_motion_bridge_hips_target = bpy.props.StringProperty(
        name="Hips Target", default=""
    )
    bpy.types.Scene.blendcap_motion_bridge_ik_protected = bpy.props.IntProperty(
        name="IK Protected", default=0
    )
    bpy.types.Scene.blendcap_motion_bridge_cancel_protected = bpy.props.IntProperty(
        name="Leg Cancel Protected", default=0
    )
    bpy.types.Scene.blendcap_motion_bridge_vmd_target = bpy.props.PointerProperty(
        name="VMD Armature", type=bpy.types.Object
    )
    bpy.types.Scene.blendcap_motion_bridge_vmd_ik_disabled = bpy.props.IntProperty(
        name="VMD Leg IK Disabled", default=0
    )
    bpy.types.Scene.blendcap_motion_bridge_vmd_cancel_disabled = bpy.props.IntProperty(
        name="VMD Leg Cancel Disabled", default=0
    )
    bpy.types.Scene.blendcap_motion_bridge_vmd_deform_relinked = bpy.props.IntProperty(
        name="VMD Leg Deform Re-linked", default=0
    )
    bpy.types.Scene.blendcap_motion_bridge_status = bpy.props.StringProperty(
        name="Status", default="尚未准备传统 BVH → MMD 映射"
    )
    bpy.types.Scene.blendcap_motion_bridge_status_level = bpy.props.EnumProperty(
        name="Status Level",
        items=(("INFO", "Info", ""), ("READY", "Ready", ""), ("ERROR", "Error", "")),
        default="INFO",
        options={"HIDDEN"},
    )
    bpy.types.Scene.blendcap_motion_bridge_critical_missing = bpy.props.StringProperty(
        name="Critical Missing", default=""
    )
    bpy.types.Scene.blendcap_motion_bridge_mapping_signature = bpy.props.StringProperty(
        name="Mapping Signature", default="", options={"HIDDEN"}
    )
    bpy.types.Scene.blendcap_motion_bridge_mapping_source = bpy.props.StringProperty(
        name="Mapping Source", default="", options={"HIDDEN"}
    )
    bpy.types.Scene.blendcap_motion_bridge_mapping_target = bpy.props.StringProperty(
        name="Mapping Target", default="", options={"HIDDEN"}
    )
    bpy.types.Scene.blendcap_motion_bridge_mapping_source_object = bpy.props.PointerProperty(
        name="Prepared Source", type=bpy.types.Object, options={"HIDDEN"}
    )
    bpy.types.Scene.blendcap_motion_bridge_mapping_target_object = bpy.props.PointerProperty(
        name="Prepared Target", type=bpy.types.Object, options={"HIDDEN"}
    )
    bpy.types.Scene.blendcap_motion_bridge_last_backup = bpy.props.StringProperty(
        name="Preset Backup", default="", options={"HIDDEN"}
    )
    bpy.types.Scene.blendcap_motion_bridge_constraint_snapshot = bpy.props.StringProperty(
        name="Constraint Snapshot", default="", options={"HIDDEN"}
    )
    bpy.types.Scene.blendcap_motion_bridge_constraint_target = bpy.props.PointerProperty(
        name="Constraint Target", type=bpy.types.Object, options={"HIDDEN"}
    )
    bpy.types.Scene.blendcap_motion_bridge_previous_target = bpy.props.PointerProperty(
        name="Previous Target", type=bpy.types.Object, options={"HIDDEN"}
    )
    bpy.types.Scene.blendcap_motion_bridge_previous_action = bpy.props.PointerProperty(
        name="Previous Action", type=bpy.types.Action, options={"HIDDEN"}
    )
    bpy.types.Scene.blendcap_motion_bridge_previous_action_name = bpy.props.StringProperty(
        name="Previous Action Name", default="", options={"HIDDEN"}
    )
    bpy.types.Scene.blendcap_motion_bridge_previous_action_slot = bpy.props.StringProperty(
        name="Previous Action Slot", default="", options={"HIDDEN"}
    )
    bpy.types.Scene.blendcap_motion_bridge_previous_use_nla = bpy.props.BoolProperty(
        name="Previous Use NLA", default=False, options={"HIDDEN"}
    )
    bpy.types.Scene.blendcap_motion_bridge_previous_action_fake_user = bpy.props.BoolProperty(
        name="Previous Action Fake User", default=False, options={"HIDDEN"}
    )
    bpy.types.Scene.blendcap_motion_bridge_previous_state_available = bpy.props.BoolProperty(
        name="Previous State Available", default=False, options={"HIDDEN"}
    )
    bpy.types.Scene.blendcap_motion_bridge_last_output_action = bpy.props.StringProperty(
        name="Last Output Action", default="", options={"HIDDEN"}
    )
    bpy.types.Scene.blendcap_motion_bridge_previous_table_json = bpy.props.StringProperty(
        name="Previous BlendCap Table", default="", options={"HIDDEN"}
    )
    for cls in operators.CLASSES:
        bpy.utils.register_class(cls)
    for cls in panels.CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(panels.CLASSES):
        bpy.utils.unregister_class(cls)
    for cls in reversed(operators.CLASSES):
        bpy.utils.unregister_class(cls)
    for name in (
        "blendcap_motion_bridge_matched",
        "blendcap_motion_bridge_total",
        "blendcap_motion_bridge_unmatched",
        "blendcap_motion_bridge_last_preset",
        "blendcap_motion_bridge_face_npz",
        "blendcap_motion_bridge_face_mesh",
        "blendcap_motion_bridge_face_matched",
        "blendcap_motion_bridge_face_total",
        "blendcap_motion_bridge_hips_target",
        "blendcap_motion_bridge_ik_protected",
        "blendcap_motion_bridge_cancel_protected",
        "blendcap_motion_bridge_vmd_target",
        "blendcap_motion_bridge_vmd_ik_disabled",
        "blendcap_motion_bridge_vmd_cancel_disabled",
        "blendcap_motion_bridge_vmd_deform_relinked",
        "blendcap_motion_bridge_status",
        "blendcap_motion_bridge_status_level",
        "blendcap_motion_bridge_critical_missing",
        "blendcap_motion_bridge_mapping_signature",
        "blendcap_motion_bridge_mapping_source",
        "blendcap_motion_bridge_mapping_target",
        "blendcap_motion_bridge_mapping_source_object",
        "blendcap_motion_bridge_mapping_target_object",
        "blendcap_motion_bridge_last_backup",
        "blendcap_motion_bridge_constraint_snapshot",
        "blendcap_motion_bridge_constraint_target",
        "blendcap_motion_bridge_previous_target",
        "blendcap_motion_bridge_previous_action",
        "blendcap_motion_bridge_previous_action_name",
        "blendcap_motion_bridge_previous_action_slot",
        "blendcap_motion_bridge_previous_use_nla",
        "blendcap_motion_bridge_previous_action_fake_user",
        "blendcap_motion_bridge_previous_state_available",
        "blendcap_motion_bridge_last_output_action",
        "blendcap_motion_bridge_previous_table_json",
    ):
        delattr(bpy.types.Scene, name)
