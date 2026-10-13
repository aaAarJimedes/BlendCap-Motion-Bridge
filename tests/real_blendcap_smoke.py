"""Opt-in isolated smoke using the real installed BlendCap retarget engine.

Run with Blender --background --factory-startup, isolated BLENDER_USER_* paths,
and BCMB_REAL_TEST_ROOT/BCMB_BLENDCAP_DIR environment variables. The test creates
synthetic rigs only; it does not load a user scene or run video inference.
"""

import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import tomllib

import bpy


SOURCE = Path(os.environ.get("BCMB_BRIDGE_PARENT", Path(__file__).resolve().parents[1])).resolve()
RUN = Path(os.environ["BCMB_REAL_TEST_ROOT"]).resolve()
BACKEND = Path(os.environ["BCMB_BLENDCAP_DIR"]).resolve()
CONFIG = Path(bpy.utils.user_resource("CONFIG")).resolve()
assert bpy.app.background
assert "--factory-startup" in sys.argv
assert not bpy.data.filepath, "Do not run against a user scene"
assert CONFIG.is_relative_to(RUN), "Test must use an isolated Blender profile"
for environment_name in ("BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS",
                         "BLENDER_USER_DATAFILES", "BLENDER_USER_EXTENSIONS"):
    environment_path = Path(os.environ[environment_name]).resolve()
    assert environment_path != RUN and environment_path.is_relative_to(RUN), environment_name
sys.dont_write_bytecode = True

backend_manifest = tomllib.loads((BACKEND / "blender_manifest.toml").read_text(encoding="utf-8"))
spec = importlib.util.spec_from_file_location(
    "bcmb_real_backend", BACKEND / "__init__.py", submodule_search_locations=[str(BACKEND)]
)
backend = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = backend
spec.loader.exec_module(backend)
sys.path.insert(0, str(SOURCE))
import blendcap_motion_bridge as bridge

assert Path(bridge.__file__).resolve().parent == SOURCE / "blendcap_motion_bridge"


def armature(name, specs):
    data = bpy.data.armatures.new(name + "Data")
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for bone_name, parent, head, tail in specs:
        bone = data.edit_bones.new(bone_name)
        bone.head, bone.tail = head, tail
        if parent:
            bone.parent = data.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


specs = [
    ("Hips", None, (0, 0, 1), (0, 0, 1.15)),
    ("Spine", "Hips", (0, 0, 1.15), (0, 0, 1.35)),
    ("Spine1", "Spine", (0, 0, 1.35), (0, 0, 1.55)),
    ("Neck", "Spine1", (0, 0, 1.55), (0, 0, 1.7)),
    ("Head", "Neck", (0, 0, 1.7), (0, 0, 1.9)),
]
for side, sign in (("Left", 1), ("Right", -1)):
    specs.extend([
        (side + "Arm", "Spine1", (sign * .15, 0, 1.5), (sign * .45, 0, 1.5)),
        (side + "ForeArm", side + "Arm", (sign * .45, 0, 1.5), (sign * .7, 0, 1.5)),
        (side + "Hand", side + "ForeArm", (sign * .7, 0, 1.5), (sign * .8, 0, 1.5)),
        (side + "UpLeg", "Hips", (sign * .1, 0, 1), (sign * .1, 0, .55)),
        (side + "Leg", side + "UpLeg", (sign * .1, 0, .55), (sign * .1, 0, .1)),
        (side + "Foot", side + "Leg", (sign * .1, 0, .1), (sign * .1, -.15, .05)),
    ])
names = {
    "Hips": "腰", "Spine": "下半身", "Spine1": "上半身", "Neck": "首", "Head": "頭",
}
for side, suffix in (("Left", ".L"), ("Right", ".R")):
    for english, japanese in (("Arm", "腕"), ("ForeArm", "ひじ"), ("Hand", "手首"),
                              ("UpLeg", "足"), ("Leg", "ひざ"), ("Foot", "足首")):
        names[side + english] = japanese + suffix


def curves(action, obj, minimum=-float("inf")):
    slot = getattr(obj.animation_data, "action_slot", None)
    return {
        (curve.data_path, curve.array_index): [
            (float(key.co.x), float(key.co.y), key.interpolation)
            for key in curve.keyframe_points if key.co.x >= minimum
        ]
        for curve in bridge.operators._action_fcurves(action, slot)
    }


registered_backend = registered_bridge = False
try:
    backend.register()
    registered_backend = True
    bridge.register()
    registered_bridge = True
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 10
    source = armature("BCMB_Smoke_BVH", specs)
    target_specs = [("センター", None, (0, 0, 0), (0, 0, .2))]
    target_specs += [(names[name], names[parent] if parent else "センター", head, tail)
                     for name, parent, head, tail in specs]
    target = armature("BCMB_Smoke_MMD", target_specs)
    for frame, angle in ((1, .15), (5, .55), (10, -.1)):
        source.pose.bones["LeftArm"].rotation_mode = "XYZ"
        source.pose.bones["LeftArm"].rotation_euler.z = angle
        source.pose.bones["LeftArm"].keyframe_insert("rotation_euler", frame=frame)
        source.pose.bones["Hips"].location.x = (frame - 1) * .03
        source.pose.bones["Hips"].keyframe_insert("location", frame=frame)
    source_action = source.animation_data.action
    source_before = curves(source_action, source)
    target.pose.bones["腕.L"].rotation_mode = "XYZ"
    target.pose.bones["腕.L"].rotation_euler.z = -.2
    target.pose.bones["腕.L"].keyframe_insert("rotation_euler", frame=1)
    previous = target.animation_data.action
    previous_before = curves(previous, target)
    scene.blendcap_retarget_source = source
    scene.blendcap_retarget_target = target
    scene.blendcap_retarget_auto_scale = False
    scene.blendcap_motion_bridge_preroll_enabled = False
    scene.frame_set(1)
    assert bpy.ops.blendcap_motion_bridge.quick_retarget() == {"FINISHED"}
    baseline = target.animation_data.action
    assert baseline != previous
    baseline_curves = curves(baseline, target, minimum=1)
    assert baseline_curves and any(len(keys) >= 10 for keys in baseline_curves.values())
    assert all(math.isfinite(value) for keys in baseline_curves.values() for _, value, _ in keys)
    assert any(max(v for _, v, _ in keys) - min(v for _, v, _ in keys) > .01
               for (path, _), keys in baseline_curves.items() if "rotation" in path and keys)
    assert bpy.ops.blendcap_motion_bridge.restore_previous_state() == {"FINISHED"}
    assert target.animation_data.action == previous
    assert curves(previous, target) == previous_before

    scene.blendcap_motion_bridge_preroll_enabled = True
    scene.blendcap_motion_bridge_preroll_pose_source = "REST"
    scene.blendcap_motion_bridge_preroll_hold_frames = 8
    scene.blendcap_motion_bridge_preroll_transition_frames = 22
    scene.frame_set(1)
    assert bpy.ops.blendcap_motion_bridge.quick_retarget() == {"FINISHED"}
    output = target.animation_data.action
    assert scene.blendcap_motion_bridge_preroll_start == -29
    assert scene.blendcap_motion_bridge_preroll_motion_start == 1
    assert scene.blendcap_motion_bridge_preroll_simulated
    assert curves(output, target, minimum=1) == baseline_curves, "Pre-roll changed real motion keys"
    assert min(frame for keys in curves(output, target).values() for frame, _, _ in keys) == -29
    scene.blendcap_motion_bridge_preroll_cleanup_confirmed = True
    assert bpy.ops.blendcap_motion_bridge.cleanup_preroll() == {"FINISHED"}
    assert curves(output, target) == baseline_curves, "Cleanup changed real motion"
    assert bpy.ops.blendcap_motion_bridge.restore_previous_state() == {"FINISHED"}
    assert target.animation_data.action == previous
    assert curves(previous, target) == previous_before
    assert source.animation_data.action == source_action
    assert curves(source_action, source) == source_before
    print("BCMB_REAL_BLENDCAP_SMOKE=" + json.dumps({
        "status": "PASS", "blender": bpy.app.version_string,
        "blendcap": backend_manifest["version"], "bridge": list(bridge.bl_info["version"]),
        "backend": "real BlendCap operator", "synthetic_rigs": True,
        "frames": [1, 10], "curves": len(baseline_curves),
        "formal_keys": sum(len(keys) for keys in baseline_curves.values()),
        "preroll": [-29, 0], "motion_keys_unchanged": True, "restore": "PASS",
        "physics_collision_tested": False,
    }, ensure_ascii=False))
finally:
    if registered_bridge:
        bridge.unregister()
    if registered_backend:
        backend.unregister()
