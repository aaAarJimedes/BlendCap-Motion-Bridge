"""Isolated Blender 5.1 integration regression for BlendCap Motion Bridge 0.3.0.

This test source-imports the development add-on under ``--factory-startup``
and supplies only the narrow BlendCap RNA/operator surface BlendCap Motion Bridge uses.
It must never load an installed add-on or write a user retarget preset.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import traceback

import bpy


if not bpy.app.background:
    raise RuntimeError("integration_030_factory.py is background-only")


TEST_DIR = Path(__file__).resolve().parent
DEV_ROOT = TEST_DIR.parent.resolve()
PACKAGE_ROOT = (DEV_ROOT / "blendcap_motion_bridge").resolve()
RUN_ROOT = Path(os.environ.get("BCMB_TEST_ROOT", "")).resolve()
CONFIG_ROOT = Path(bpy.utils.user_resource("CONFIG")).resolve()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


if not os.environ.get("BCMB_TEST_ROOT"):
    raise RuntimeError("BCMB_TEST_ROOT must name the isolated run directory")
if not _is_relative_to(RUN_ROOT, TEST_DIR):
    raise RuntimeError(f"test root escaped tests directory: {RUN_ROOT}")
if not _is_relative_to(CONFIG_ROOT, RUN_ROOT):
    raise RuntimeError(
        f"Blender CONFIG is not isolated: CONFIG={CONFIG_ROOT}, run={RUN_ROOT}"
    )


sys.path.insert(0, str(DEV_ROOT))
import blendcap_motion_bridge  # noqa: E402


if Path(blendcap_motion_bridge.__file__).resolve().parent != PACKAGE_ROOT:
    raise RuntimeError(f"did not source-import development add-on: {blendcap_motion_bridge.__file__}")
if tuple(blendcap_motion_bridge.bl_info["version"]) != (0, 3, 0):
    raise RuntimeError(f"unexpected add-on version: {blendcap_motion_bridge.bl_info['version']}")


class TEST_PG_blendcap_pair(bpy.types.PropertyGroup):
    source: bpy.props.StringProperty(default="")
    target: bpy.props.StringProperty(default="")
    channels: bpy.props.EnumProperty(
        items=(
            ("ROT", "Rotation", ""),
            ("LOC", "Location", ""),
            ("LOC_ROT", "Both", ""),
        ),
        default="ROT",
    )
    axes: bpy.props.StringProperty(default="XYZ")
    influence: bpy.props.FloatProperty(default=1.0, min=0.0, max=1.0)


FAKE_BAKE = {
    "calls": 0,
    "mode": "plain",
    "target": None,
    "leg": None,
    "leg_muted": None,
    "cancel": None,
    "unrelated_ik": None,
    "unrelated_transform": None,
}


class TEST_OT_blendcap_apply_retarget(bpy.types.Operator):
    bl_idname = "blendcap.apply_retarget"
    bl_label = "BlendCap Motion Bridge Test Bake"

    def execute(self, context):
        FAKE_BAKE["calls"] += 1
        target = context.scene.blendcap_retarget_target
        if target is None or target.type != "ARMATURE":
            raise RuntimeError("fake BlendCap received no target")
        if FAKE_BAKE["target"] is not None and target != FAKE_BAKE["target"]:
            raise RuntimeError("fake BlendCap received the wrong target")

        if FAKE_BAKE["mode"] == "fk":
            leg = FAKE_BAKE["leg"]
            leg_muted = FAKE_BAKE["leg_muted"]
            cancel = FAKE_BAKE["cancel"]
            unrelated_ik = FAKE_BAKE["unrelated_ik"]
            unrelated_transform = FAKE_BAKE["unrelated_transform"]
            if not leg.mute or abs(float(leg.influence)) > 1e-8:
                raise RuntimeError("active leg IK was not disabled before bake")
            if not leg_muted.mute or abs(float(leg_muted.influence)) > 1e-8:
                raise RuntimeError("pre-muted leg IK was not transactionally disabled")
            if not cancel.mute or abs(float(cancel.influence)) > 1e-8:
                raise RuntimeError("waist-cancel constraint was not disabled before bake")
            if unrelated_ik.mute or abs(float(unrelated_ik.influence) - 0.37) > 1e-6:
                raise RuntimeError("unrelated arm IK changed before bake")
            if unrelated_transform.mute or abs(float(unrelated_transform.influence) - 0.58) > 1e-6:
                raise RuntimeError("unrelated TRANSFORM changed before bake")

        action = bpy.data.actions.new(f"TEST_BlendCap_Output_{FAKE_BAKE['calls']}")
        animation_data = target.animation_data_create()
        blendcap_motion_bridge.operators._bind_action(animation_data, action)
        return {"FINISHED"}


FAKE_CLASSES = (TEST_PG_blendcap_pair, TEST_OT_blendcap_apply_retarget)
FAKE_SCENE_PROPERTIES = (
    "blendcap_retarget_source",
    "blendcap_retarget_target",
    "blendcap_retarget_pairs",
    "blendcap_retarget_preset",
    "blendcap_retarget_source_prefix",
    "blendcap_retarget_namespace_strip",
    "blendcap_retarget_auto_bake_ik",
)


def register_fake_blendcap() -> None:
    for cls in FAKE_CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.blendcap_retarget_source = bpy.props.PointerProperty(
        type=bpy.types.Object
    )
    bpy.types.Scene.blendcap_retarget_target = bpy.props.PointerProperty(
        type=bpy.types.Object
    )
    bpy.types.Scene.blendcap_retarget_pairs = bpy.props.CollectionProperty(
        type=TEST_PG_blendcap_pair
    )
    bpy.types.Scene.blendcap_retarget_preset = bpy.props.StringProperty(
        default="__UNSAVED__"
    )
    bpy.types.Scene.blendcap_retarget_source_prefix = bpy.props.StringProperty(
        default=""
    )
    bpy.types.Scene.blendcap_retarget_namespace_strip = bpy.props.StringProperty(
        default=""
    )
    bpy.types.Scene.blendcap_retarget_auto_bake_ik = bpy.props.BoolProperty(
        default=True
    )


def unregister_fake_blendcap() -> None:
    for name in reversed(FAKE_SCENE_PROPERTIES):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
    for cls in reversed(FAKE_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass


SOURCE_REQUIRED = (
    "Hips",
    "Spine",
    "Spine1",
    "Neck",
    "Head",
    "LeftArm",
    "LeftForeArm",
    "LeftHand",
    "RightArm",
    "RightForeArm",
    "RightHand",
    "LeftUpLeg",
    "LeftLeg",
    "LeftFoot",
    "RightUpLeg",
    "RightLeg",
    "RightFoot",
)


SOMA_REQUIRED = (
    "Hips",
    "Spine1",
    "Spine2",
    "Chest",
    "Neck1",
    "Neck2",
    "Head",
    "LeftArm",
    "LeftForeArm",
    "LeftHand",
    "RightArm",
    "RightForeArm",
    "RightHand",
    "LeftLeg",
    "LeftShin",
    "LeftFoot",
    "RightLeg",
    "RightShin",
    "RightFoot",
)


TARGET_SPECS = (
    ("センター", None),
    ("腰", "センター"),
    ("下半身", "腰"),
    ("上半身", "下半身"),
    ("首", "上半身"),
    ("頭", "首"),
    ("腕.L", "上半身"),
    ("ひじ.L", "腕.L"),
    ("手首.L", "ひじ.L"),
    ("腕.R", "上半身"),
    ("ひじ.R", "腕.R"),
    ("手首.R", "ひじ.R"),
    ("足.L", "腰"),
    ("ひざ.L", "足.L"),
    ("足首.L", "ひざ.L"),
    ("足.R", "腰"),
    ("ひざ.R", "足.R"),
    ("足首.R", "ひざ.R"),
    ("足IK.L", "センター"),
    ("足IK.R", "センター"),
    ("手IK.L", "上半身"),
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def blocked_call(operator, expected_text: str):
    """Call an operator whose ERROR+CANCELLED may surface as RuntimeError."""
    try:
        result = operator("EXEC_DEFAULT")
    except RuntimeError as exc:
        message = str(exc)
        check(expected_text in message, f"unexpected blocking error: {message}")
        return {"CANCELLED"}, message
    return result, ""


def create_armature(name: str, specs) -> bpy.types.Object:
    data = bpy.data.armatures.new(name + "_DATA")
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bones = {}
    for index, spec in enumerate(specs):
        bone_name, parent_name = spec
        bone = data.edit_bones.new(bone_name)
        bone.head = (0.0, 0.0, float(index) * 0.1)
        bone.tail = (0.0, 0.05, float(index) * 0.1 + 0.08)
        bone.parent = bones.get(parent_name)
        bones[bone_name] = bone
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def create_source(name: str = "Legacy_BVH") -> bpy.types.Object:
    specs = []
    previous = None
    for bone_name in SOURCE_REQUIRED:
        specs.append((bone_name, previous))
        previous = bone_name
    return create_armature(name, specs)


def create_soma(name: str = "SOMA_Source") -> bpy.types.Object:
    specs = []
    previous = None
    for bone_name in SOMA_REQUIRED:
        specs.append((bone_name, previous))
        previous = bone_name
    result = create_armature(name, specs)
    result["proscenium_canonical_model"] = "kimodo-soma-rp"
    return result


def create_target(name: str = "MMD_Target") -> bpy.types.Object:
    return create_armature(name, TARGET_SPECS)


def remove_test_data() -> None:
    scene = bpy.context.scene
    if hasattr(scene, "blendcap_retarget_pairs"):
        scene.blendcap_retarget_pairs.clear()
        scene.blendcap_retarget_source = None
        scene.blendcap_retarget_target = None
        scene.blendcap_retarget_preset = "__UNSAVED__"
        scene.blendcap_retarget_source_prefix = ""
        scene.blendcap_retarget_namespace_strip = ""
        scene.blendcap_retarget_auto_bake_ik = True
    for name, value in (
        ("blendcap_motion_bridge_mapping_signature", ""),
        ("blendcap_motion_bridge_mapping_source", ""),
        ("blendcap_motion_bridge_mapping_target", ""),
        ("blendcap_motion_bridge_constraint_snapshot", ""),
        ("blendcap_motion_bridge_constraint_target", None),
        ("blendcap_motion_bridge_previous_target", None),
        ("blendcap_motion_bridge_previous_action", None),
        ("blendcap_motion_bridge_previous_action_name", ""),
        ("blendcap_motion_bridge_previous_action_slot", ""),
        ("blendcap_motion_bridge_previous_state_available", False),
        ("blendcap_motion_bridge_previous_table_json", ""),
        ("blendcap_motion_bridge_last_output_action", ""),
    ):
        if hasattr(scene, name):
            setattr(scene, name, value)
    for obj in tuple(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for action in tuple(bpy.data.actions):
        bpy.data.actions.remove(action)
    for data in tuple(bpy.data.armatures):
        if data.users == 0:
            bpy.data.armatures.remove(data)
    FAKE_BAKE.update(
        calls=0,
        mode="plain",
        target=None,
        leg=None,
        leg_muted=None,
        cancel=None,
        unrelated_ik=None,
        unrelated_transform=None,
    )


def config_files() -> set[str]:
    if not CONFIG_ROOT.exists():
        return set()
    return {
        str(path.relative_to(CONFIG_ROOT))
        for path in CONFIG_ROOT.rglob("*")
        if path.is_file()
    }


def test_prepare_in_memory() -> dict:
    remove_test_data()
    source = create_source()
    target = create_target()
    scene = bpy.context.scene
    scene.blendcap_retarget_source = source
    scene.blendcap_retarget_target = target
    stale = scene.blendcap_retarget_pairs.add()
    stale.source = "OldSource"
    stale.target = "OldTarget"
    files_before = config_files()

    result = bpy.ops.blendcap_motion_bridge.prepare_in_memory("EXEC_DEFAULT")

    check(result == {"FINISHED"}, f"prepare_in_memory failed: {result}")
    check(scene.blendcap_motion_bridge_status_level == "READY", scene.blendcap_motion_bridge_status)
    check(scene.blendcap_motion_bridge_mapping_source == source.name, "mapping source not recorded")
    check(scene.blendcap_motion_bridge_mapping_target == target.name, "mapping target not recorded")
    check(bool(scene.blendcap_motion_bridge_mapping_signature), "mapping signature missing")
    check(len(scene.blendcap_retarget_pairs) >= 18, "validated table is unexpectedly short")
    check(
        not any(pair.source == "OldSource" for pair in scene.blendcap_retarget_pairs),
        "stale table row survived prepare_in_memory",
    )
    check(config_files() == files_before, "prepare_in_memory wrote into Blender CONFIG")
    return {"pairs": len(scene.blendcap_retarget_pairs)}


def test_soma_hard_block() -> dict:
    remove_test_data()
    source = create_soma()
    target = create_target()
    scene = bpy.context.scene
    scene.blendcap_retarget_source = source
    scene.blendcap_retarget_target = target
    sentinel = scene.blendcap_retarget_pairs.add()
    sentinel.source = "SentinelSource"
    sentinel.target = "SentinelTarget"

    result, operator_error = blocked_call(
        bpy.ops.blendcap_motion_bridge.prepare_in_memory,
        "SOMA",
    )

    check(result == {"CANCELLED"}, f"SOMA source was not blocked: {result}")
    check(
        "SOMA" in scene.blendcap_motion_bridge_status
        and "Motion Bridge" in scene.blendcap_motion_bridge_status,
        f"SOMA guidance missing: {scene.blendcap_motion_bridge_status}",
    )
    check("SOMA" in operator_error or result == {"CANCELLED"}, "SOMA call was not blocked")
    check(len(scene.blendcap_retarget_pairs) == 1, "SOMA block mutated pair table")
    check(scene.blendcap_retarget_pairs[0].source == "SentinelSource", "sentinel row changed")
    check(FAKE_BAKE["calls"] == 0, "SOMA block reached BlendCap bake")
    return {"status": scene.blendcap_motion_bridge_status}


def test_stale_pair_table_block() -> dict:
    remove_test_data()
    source = create_source()
    target = create_target()
    scene = bpy.context.scene
    scene.blendcap_retarget_source = source
    scene.blendcap_retarget_target = target
    check(
        bpy.ops.blendcap_motion_bridge.prepare_in_memory("EXEC_DEFAULT") == {"FINISHED"},
        "fixture prepare failed",
    )
    scene.blendcap_retarget_pairs[0].target = "StaleTargetBone"
    calls_before = FAKE_BAKE["calls"]

    result, operator_error = blocked_call(
        bpy.ops.blendcap_motion_bridge.apply_retarget_fk_safe,
        "pair table",
    )

    check(result == {"CANCELLED"}, f"stale pair table was accepted: {result}")
    check("pair table" in operator_error or result == {"CANCELLED"}, "stale pair call was not blocked")
    check(FAKE_BAKE["calls"] == calls_before, "stale pair table reached BlendCap bake")
    check("pair table" in scene.blendcap_motion_bridge_status, scene.blendcap_motion_bridge_status)
    return {"status": scene.blendcap_motion_bridge_status}


def test_stale_target_signature_block() -> dict:
    remove_test_data()
    source = create_source()
    original_target = create_target("MMD_Target_A")
    scene = bpy.context.scene
    scene.blendcap_retarget_source = source
    scene.blendcap_retarget_target = original_target
    check(
        bpy.ops.blendcap_motion_bridge.prepare_in_memory("EXEC_DEFAULT") == {"FINISHED"},
        "fixture prepare failed",
    )
    recorded_signature = scene.blendcap_motion_bridge_mapping_signature
    clone_target = create_target("MMD_Target_B")
    scene.blendcap_retarget_target = clone_target
    FAKE_BAKE["target"] = clone_target
    calls_before = FAKE_BAKE["calls"]

    result, operator_error = blocked_call(
        bpy.ops.blendcap_motion_bridge.apply_retarget_fk_safe,
        "未授权",
    )

    check(
        result == {"CANCELLED"},
        "pair table prepared for target A was accepted for same-named bones on target B",
    )
    check("未授权" in operator_error or result == {"CANCELLED"}, "stale target call was not blocked")
    check(FAKE_BAKE["calls"] == calls_before, "stale target signature reached BlendCap bake")
    check(
        scene.blendcap_motion_bridge_mapping_signature == recorded_signature,
        "validation silently refreshed stale authorization signature",
    )
    return {"status": scene.blendcap_motion_bridge_status}


def add_fk_constraints(target: bpy.types.Object) -> dict:
    leg = target.pose.bones["ひざ.L"].constraints.new("IK")
    leg.name = "LegIK.Active"
    leg.target = target
    leg.subtarget = "足IK.L"
    leg.influence = 0.65

    leg_muted = target.pose.bones["ひざ.R"].constraints.new("IK")
    leg_muted.name = "LegIK.PreMuted"
    leg_muted.target = target
    leg_muted.subtarget = "足IK.R"
    leg_muted.mute = True
    leg_muted.influence = 0.25

    unrelated_ik = target.pose.bones["腕.L"].constraints.new("IK")
    unrelated_ik.name = "ArmIK.Unrelated"
    unrelated_ik.target = target
    unrelated_ik.subtarget = "手IK.L"
    unrelated_ik.influence = 0.37

    cancel = target.pose.bones["腰"].constraints.new("TRANSFORM")
    cancel.name = "waist_cancel"
    cancel.target = target
    cancel.subtarget = "センター"
    cancel.influence = 0.42

    unrelated_transform = target.pose.bones["腰"].constraints.new("TRANSFORM")
    unrelated_transform.name = "torso_follow_unrelated"
    unrelated_transform.target = target
    unrelated_transform.subtarget = "センター"
    unrelated_transform.influence = 0.58

    return {
        "leg": leg,
        "leg_muted": leg_muted,
        "unrelated_ik": unrelated_ik,
        "cancel": cancel,
        "unrelated_transform": unrelated_transform,
    }


def test_fk_safe_and_restore() -> dict:
    remove_test_data()
    source = create_source()
    target = create_target()
    scene = bpy.context.scene
    scene.blendcap_retarget_source = source
    scene.blendcap_retarget_target = target
    old_pair = scene.blendcap_retarget_pairs.add()
    old_pair.source = "BaselineSource"
    old_pair.target = "BaselineTarget"
    old_pair.channels = "ROT"
    old_pair.axes = "XZ"
    old_pair.influence = 0.73
    constraints = add_fk_constraints(target)
    baseline = bpy.data.actions.new("TEST_Baseline_Action")
    baseline.use_fake_user = False
    animation_data = target.animation_data_create()
    blendcap_motion_bridge.operators._bind_action(animation_data, baseline)
    animation_data.use_nla = False
    scene.blendcap_retarget_auto_bake_ik = True
    FAKE_BAKE.update(mode="fk", target=target, **constraints)

    result = bpy.ops.blendcap_motion_bridge.quick_retarget("EXEC_DEFAULT")

    check(result == {"FINISHED"}, f"quick FK-safe retarget failed: {result}")
    output = animation_data.action
    check(output is not None and output != baseline, "independent output Action was not created")
    check(output.get("blendcap_motion_bridge_role") == "RETARGET_OUTPUT", "output ownership tag missing")
    check(constraints["leg"].mute and constraints["leg"].influence == 0.0, "leg IK not held off")
    check(
        constraints["leg_muted"].mute and constraints["leg_muted"].influence == 0.0,
        "pre-muted leg IK not held off",
    )
    check(constraints["cancel"].mute and constraints["cancel"].influence == 0.0, "waist cancel not held off")
    check(
        not constraints["unrelated_ik"].mute
        and abs(constraints["unrelated_ik"].influence - 0.37) < 1e-6,
        "unrelated arm IK was modified",
    )
    check(
        not constraints["unrelated_transform"].mute
        and abs(constraints["unrelated_transform"].influence - 0.58) < 1e-6,
        "unrelated TRANSFORM was modified",
    )
    check(scene.blendcap_retarget_auto_bake_ik is True, "auto-bake IK flag not restored")
    check(bool(scene.blendcap_motion_bridge_constraint_snapshot), "constraint baseline was not saved")
    check(scene.blendcap_motion_bridge_previous_state_available, "target animation baseline missing")
    check(bool(scene.blendcap_motion_bridge_previous_table_json), "previous BlendCap table was not saved")

    restore = bpy.ops.blendcap_motion_bridge.restore_previous_state("EXEC_DEFAULT")

    check(restore == {"FINISHED"}, f"baseline restore failed: {restore}")
    check(animation_data.action == baseline, "baseline Action was not restored")
    check(not baseline.use_fake_user, "baseline fake-user flag was not restored")
    check(not constraints["leg"].mute and abs(constraints["leg"].influence - 0.65) < 1e-6, "active leg IK baseline lost")
    check(constraints["leg_muted"].mute and abs(constraints["leg_muted"].influence - 0.25) < 1e-6, "pre-muted leg IK baseline lost")
    check(not constraints["cancel"].mute and abs(constraints["cancel"].influence - 0.42) < 1e-6, "waist-cancel baseline lost")
    check(not constraints["unrelated_ik"].mute and abs(constraints["unrelated_ik"].influence - 0.37) < 1e-6, "unrelated arm IK changed during restore")
    check(not constraints["unrelated_transform"].mute and abs(constraints["unrelated_transform"].influence - 0.58) < 1e-6, "unrelated TRANSFORM changed during restore")
    check(not scene.blendcap_motion_bridge_constraint_snapshot, "constraint snapshot not cleared")
    check(not scene.blendcap_motion_bridge_previous_state_available, "animation baseline not cleared")
    check(not scene.blendcap_motion_bridge_previous_table_json, "previous BlendCap table snapshot not cleared")
    check(len(scene.blendcap_retarget_pairs) == 1, "previous BlendCap pair count was not restored")
    restored_pair = scene.blendcap_retarget_pairs[0]
    check(restored_pair.source == "BaselineSource", "previous BlendCap source pair was not restored")
    check(restored_pair.target == "BaselineTarget", "previous BlendCap target pair was not restored")
    check(restored_pair.channels == "ROT", "previous BlendCap channels were not restored")
    check(restored_pair.axes == "XZ", "previous BlendCap axes were not restored")
    check(abs(restored_pair.influence - 0.73) < 1e-6, "previous BlendCap influence was not restored")
    check(bpy.data.actions.get(output.name) == output, "output Action should remain after restore")
    return {
        "quick_retarget": "FINISHED",
        "output": output.name,
        "fake_bake_calls": FAKE_BAKE["calls"],
        "restored_leg_influence": constraints["leg"].influence,
        "restored_table_pairs": len(scene.blendcap_retarget_pairs),
    }


TESTS = (
    ("prepare_in_memory", test_prepare_in_memory),
    ("soma_hard_block", test_soma_hard_block),
    ("stale_pair_table_block", test_stale_pair_table_block),
    ("stale_target_signature_block", test_stale_target_signature_block),
    ("fk_safe_and_restore", test_fk_safe_and_restore),
)


def main() -> None:
    results = {}
    failures = {}
    registered_fake = False
    registered_addon = False
    try:
        register_fake_blendcap()
        registered_fake = True
        blendcap_motion_bridge.register()
        registered_addon = True
        for name, test in TESTS:
            try:
                results[name] = test()
            except Exception as exc:  # Continue to expose independent regressions.
                failures[name] = {
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
    finally:
        remove_test_data()
        if registered_addon:
            blendcap_motion_bridge.unregister()
        if registered_fake:
            unregister_fake_blendcap()

    report = {
        "status": "PASS" if not failures else "FAIL",
        "addon": str(Path(blendcap_motion_bridge.__file__).resolve()),
        "version": list(blendcap_motion_bridge.bl_info["version"]),
        "blender": bpy.app.version_string,
        "config": str(CONFIG_ROOT),
        "results": results,
        "failures": failures,
    }
    print("BLENDCAP_MOTION_BRIDGE_INTEGRATION_030=" + json.dumps(report, ensure_ascii=False))
    if failures:
        raise RuntimeError(
            "BlendCap Motion Bridge 0.3.0 integration regression(s): "
            + ", ".join(sorted(failures))
        )


if __name__ == "__main__":
    main()
