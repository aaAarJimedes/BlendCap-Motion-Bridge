"""Safe operators for traditional BlendCap BVH -> MMD workflows."""

import hashlib
import json
import os

import bpy

from . import face_mapper
from . import mmd_mapper
from . import preset_writer


def _bone_names(rig):
    if rig is None or rig.type != "ARMATURE":
        return []
    return [b.name for b in rig.data.bones]


def _bone_parents(rig):
    if rig is None or rig.type != "ARMATURE":
        return {}
    return {
        b.name: b.parent.name if b.parent is not None else None
        for b in rig.data.bones
    }


def _bone_aliases(rig):
    aliases = {}
    if rig is None or rig.type != "ARMATURE":
        return aliases
    for bone in rig.data.bones:
        values = []
        holders = [bone]
        pose_bone = rig.pose.bones.get(bone.name) if rig.pose else None
        if pose_bone is not None:
            holders.append(pose_bone)
        for holder in holders:
            metadata = getattr(holder, "mmd_bone", None)
            if metadata is None or getattr(metadata, "is_controllable", True) is False:
                continue
            for attr in ("name_j", "name_e"):
                value = getattr(metadata, attr, "")
                if isinstance(value, str) and value.strip():
                    values.append(value.strip())
        aliases[bone.name] = tuple(dict.fromkeys(values))
    return aliases


def _source_profile(rig):
    if rig is None or rig.type != "ARMATURE":
        return "UNKNOWN"
    if rig.get("proscenium_canonical_model") == "kimodo-soma-rp":
        return "SOMA_CANONICAL"
    return mmd_mapper.detect_source_profile(_bone_names(rig))


def _looks_like_mmd(rig):
    if rig is None or rig.type != "ARMATURE":
        return False
    alias_count = sum(bool(values) for values in _bone_aliases(rig).values())
    if alias_count >= 4:
        return True
    names = set(_bone_names(rig))
    japanese_core = {"センター", "下半身", "上半身", "首", "頭"}
    if len(japanese_core.intersection(names)) >= 4:
        return True
    parent = rig
    seen = set()
    while parent is not None and parent.as_pointer() not in seen:
        seen.add(parent.as_pointer())
        if getattr(parent, "mmd_type", "NONE") == "ROOT":
            return True
        parent = parent.parent
    return False


def _build_pairs(source, target):
    return mmd_mapper.build_mapping(
        _bone_names(source),
        _bone_names(target),
        _bone_parents(target),
        _bone_aliases(target),
    )


def _critical_missing(source, pairs, missing):
    source_names = _bone_names(source)
    source_missing = [
        name for name in mmd_mapper.BLENDCAP_REQUIRED
        if not mmd_mapper._source_exists(name, source_names)
    ]
    optional_prefixes = ("LeftShoulder", "RightShoulder", "LeftToe", "RightToe", "Spine3")
    target_missing = [
        label for label in missing
        if not label.startswith(optional_prefixes)
        and "HandThumb" not in label
        and "HandIndex" not in label
        and "HandMiddle" not in label
        and "HandRing" not in label
        and "HandPinky" not in label
    ]
    rotation_targets = {}
    conflicts = []
    location_axes = {}
    for pair in pairs:
        target_name = pair["target"]
        channels = pair.get("channels", "ROT")
        if channels in {"ROT", "LOC_ROT"}:
            previous = rotation_targets.get(target_name)
            if previous is not None and previous != pair["source"]:
                conflicts.append(f"{target_name} 重复旋转")
            rotation_targets[target_name] = pair["source"]
        if channels in {"LOC", "LOC_ROT"}:
            axes = set(pair.get("axes", "XYZ"))
            overlap = location_axes.setdefault(target_name, set()).intersection(axes)
            if overlap:
                conflicts.append(f"{target_name} 位移轴重复")
            location_axes[target_name].update(axes)
    return tuple(dict.fromkeys(source_missing + target_missing + conflicts))


def _mapping_signature(source, target, pairs):
    payload = {
        "source": source.name,
        "source_bones": sorted(_bone_names(source)),
        "target": target.name,
        "target_bones": sorted(_bone_names(target)),
        "pairs": pairs,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _set_mapping_status(scene, source, target, pairs, missing, critical):
    scene.blendcap_motion_bridge_matched = len(pairs)
    scene.blendcap_motion_bridge_total = len(pairs) + len(missing) + sum(
        1 for name in mmd_mapper.BLENDCAP_REQUIRED
        if not mmd_mapper._source_exists(name, _bone_names(source))
    )
    scene.blendcap_motion_bridge_unmatched = ", ".join(missing)
    scene.blendcap_motion_bridge_critical_missing = "、".join(critical)
    scene.blendcap_motion_bridge_hips_target = _hips_target_from_pairs(pairs)
    if critical:
        scene.blendcap_motion_bridge_status_level = "ERROR"
        scene.blendcap_motion_bridge_status = f"关键项缺失：{'、'.join(critical[:6])}"
    else:
        scene.blendcap_motion_bridge_status_level = "READY"
        scene.blendcap_motion_bridge_status = f"传统 BVH 映射就绪：{len(pairs)} 对"


def _authorize_mapping(scene, source, target, pairs):
    """Bind the current in-memory pair table to one exact rig pair.

    Diagnostic checks must not refresh this authorization.  In particular,
    two MMD rigs can have identical bone names, so comparing pair rows alone
    cannot prove that the user prepared the currently selected object.
    """
    scene.blendcap_motion_bridge_mapping_source = source.name
    scene.blendcap_motion_bridge_mapping_target = target.name
    scene.blendcap_motion_bridge_mapping_source_object = source
    scene.blendcap_motion_bridge_mapping_target_object = target
    scene.blendcap_motion_bridge_mapping_signature = _mapping_signature(source, target, pairs)


def _auto_select_rigs(context):
    scene = context.scene
    source = getattr(scene, "blendcap_retarget_source", None)
    if _source_profile(source) != "BLENDCAP_BVH":
        candidates = [
            obj for obj in scene.objects
            if obj.type == "ARMATURE" and _source_profile(obj) == "BLENDCAP_BVH"
        ]
        active = context.active_object
        if active in candidates:
            source = active
        elif len(candidates) == 1:
            source = candidates[0]
        elif len(candidates) > 1:
            return None, None, f"检测到多个传统 BVH 来源：{'、'.join(sorted(obj.name for obj in candidates))}"
        else:
            if _source_profile(getattr(scene, "blendcap_retarget_source", None)) == "SOMA_CANONICAL":
                return None, None, "官方 SOMA 骨架必须使用 Proscenium Motion Bridge，不能走传统 BlendCap BVH 映射"
            return None, None, "未找到完整 BlendCap BVH 来源骨架"

    target = getattr(scene, "blendcap_retarget_target", None)
    if target == source or not _looks_like_mmd(target):
        candidates = [
            obj for obj in scene.objects
            if obj != source and _looks_like_mmd(obj)
        ]
        active = context.active_object
        if active in candidates:
            target = active
        elif len(candidates) == 1:
            target = candidates[0]
        elif len(candidates) > 1:
            return source, None, f"检测到多个 MMD 目标：{'、'.join(sorted(obj.name for obj in candidates))}"
        else:
            return source, None, "未找到高置信 MMD 目标骨架"
    scene.blendcap_retarget_source = source
    scene.blendcap_retarget_target = target
    return source, target, ""


def _load_pairs_in_memory(scene, source, target, pairs):
    source_prefix = mmd_mapper.detect_source_prefix(_bone_names(source), [p["source"] for p in pairs])
    scene.blendcap_retarget_source = source
    scene.blendcap_retarget_target = target
    if hasattr(scene, "blendcap_retarget_preset"):
        scene.blendcap_retarget_preset = "__UNSAVED__"
    if hasattr(scene, "blendcap_retarget_source_prefix"):
        scene.blendcap_retarget_source_prefix = source_prefix
    if hasattr(scene, "blendcap_retarget_namespace_strip"):
        scene.blendcap_retarget_namespace_strip = ""
    scene.blendcap_retarget_pairs.clear()
    for pair in pairs:
        item = scene.blendcap_retarget_pairs.add()
        item.source = pair["source"]
        item.target = pair["target"]
        item.channels = pair.get("channels", "ROT")
        if "axes" in pair and hasattr(item, "axes"):
            item.axes = pair["axes"]
        item.influence = float(pair.get("influence", 1.0))


def _prepare_mapping(context, *, load_table):
    if not _blendcap_ready():
        return None, None, None, None, "BlendCap 未启用"
    source, target, error = _auto_select_rigs(context)
    if error:
        context.scene.blendcap_motion_bridge_status_level = "ERROR"
        context.scene.blendcap_motion_bridge_status = error
        return source, target, None, None, error
    profile = _source_profile(source)
    if profile == "SOMA_CANONICAL":
        error = "官方 SOMA 骨架必须使用 BA Motion Bridge"
        context.scene.blendcap_motion_bridge_status_level = "ERROR"
        context.scene.blendcap_motion_bridge_status = error
        return source, target, None, None, error
    if profile != "BLENDCAP_BVH":
        error = "来源骨架不是完整 BlendCap BVH；已阻止猜测 LeftLeg 语义"
        context.scene.blendcap_motion_bridge_status_level = "ERROR"
        context.scene.blendcap_motion_bridge_status = error
        return source, target, None, None, error
    pairs, missing = _build_pairs(source, target)
    critical = _critical_missing(source, pairs, missing)
    _set_mapping_status(context.scene, source, target, pairs, missing, critical)
    if critical:
        return source, target, pairs, missing, context.scene.blendcap_motion_bridge_status
    if load_table:
        _load_pairs_in_memory(context.scene, source, target, pairs)
        if not _table_matches(context.scene, pairs):
            error = "内存 pair table 校验失败；未授权重定向"
            context.scene.blendcap_motion_bridge_status_level = "ERROR"
            context.scene.blendcap_motion_bridge_status = error
            return source, target, pairs, missing, error
        _authorize_mapping(context.scene, source, target, pairs)
    return source, target, pairs, missing, ""


def _serialize_pair(item):
    return {
        "source": item.source,
        "target": item.target,
        "channels": item.channels,
        "axes": getattr(item, "axes", "XYZ"),
        "influence": float(getattr(item, "influence", 1.0)),
    }


def _capture_table_state(scene):
    fields = (
        "blendcap_retarget_source", "blendcap_retarget_target", "blendcap_retarget_preset",
        "blendcap_retarget_source_prefix", "blendcap_retarget_namespace_strip",
        "blendcap_motion_bridge_mapping_source", "blendcap_motion_bridge_mapping_target",
        "blendcap_motion_bridge_mapping_source_object", "blendcap_motion_bridge_mapping_target_object",
        "blendcap_motion_bridge_mapping_signature",
    )
    return {
        "fields": {name: getattr(scene, name) for name in fields if hasattr(scene, name)},
        "pairs": [_serialize_pair(item) for item in scene.blendcap_retarget_pairs],
    }


def _restore_table_state(scene, state):
    for name, value in state["fields"].items():
        try:
            setattr(scene, name, value)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
    scene.blendcap_retarget_pairs.clear()
    for pair in state["pairs"]:
        item = scene.blendcap_retarget_pairs.add()
        item.source = pair["source"]
        item.target = pair["target"]
        item.channels = pair["channels"]
        if hasattr(item, "axes"):
            item.axes = pair["axes"]
        item.influence = pair["influence"]


def _table_state_json(state):
    fields = {}
    for name, value in state["fields"].items():
        if isinstance(value, bpy.types.Object):
            fields[name] = {"object": value.name}
        elif value is None and name in {"blendcap_retarget_source", "blendcap_retarget_target"}:
            fields[name] = {"object": None}
        elif isinstance(value, (str, bool, int, float)):
            fields[name] = value
    return json.dumps({"schema": 1, "fields": fields, "pairs": state["pairs"]}, ensure_ascii=False)


def _table_state_from_json(value):
    state = json.loads(value)
    if not isinstance(state, dict) or not isinstance(state.get("pairs"), list):
        raise ValueError("previous table snapshot is invalid")
    fields = {}
    for name, item in state.get("fields", {}).items():
        if isinstance(item, dict) and "object" in item:
            object_name = item["object"]
            fields[name] = bpy.data.objects.get(object_name) if object_name else None
        else:
            fields[name] = item
    return {"fields": fields, "pairs": state["pairs"]}


def _table_matches(scene, pairs):
    expected = {
        (pair["source"], pair["target"], pair.get("channels", "ROT"), pair.get("axes", "XYZ"))
        for pair in pairs
    }
    actual = {
        (item.source, item.target, item.channels, getattr(item, "axes", "XYZ"))
        for item in scene.blendcap_retarget_pairs
    }
    return bool(expected) and actual == expected


def _blendcap_ready():
    return hasattr(bpy.types.Scene, "blendcap_retarget_source") and hasattr(
        bpy.types.Scene, "blendcap_retarget_pairs"
    )


def _selected_rigs(scene):
    return scene.blendcap_retarget_source, scene.blendcap_retarget_target


def _hips_target_from_pairs(pairs):
    for pair in pairs:
        if pair["source"] == "Hips" and pair["channels"] == "ROT":
            return pair["target"]
    return ""


def _thigh_targets(scene, source, target):
    """Return mapped MMD thigh bone names for LeftUpLeg/RightUpLeg."""
    if _blendcap_ready():
        from_pairs = [
            p.target for p in scene.blendcap_retarget_pairs
            if getattr(p, "source", "") in ("LeftUpLeg", "RightUpLeg")
            and getattr(p, "channels", "") == "ROT"
        ]
        if len(from_pairs) == 2:
            return from_pairs
    if source is not None and target is not None:
        pairs, _missing = mmd_mapper.build_mapping(
            _bone_names(source),
            _bone_names(target),
            _bone_parents(target),
        )
        from_pairs = [
            p["target"] for p in pairs
            if p["source"] in ("LeftUpLeg", "RightUpLeg")
            and p["channels"] == "ROT"
        ]
        if len(from_pairs) == 2:
            return from_pairs
    return _direct_thigh_targets(target)


def _best_thigh_targets(scene, source, target):
    """Prefer direct name-based thigh detection over possibly stale pairs."""
    direct = _direct_thigh_targets(target)
    if len(direct) == 2:
        return direct
    return _thigh_targets(scene, source, target)


THIGH_STEMS = ("足", "腿", "大腿", "Leg", "UpLeg", "Thigh", "Femur")
LEG_IK_BONE_STEMS = (
    "ひざ", "膝", "knee", "shin",
    "足首", "足関節", "踝", "脚踝", "ankle",
)
LEG_IK_TARGET_MARKERS = (
    "足", "つま先", "脚", "脚踝", "脚尖",
    "foot", "ankle", "toe",
)


def _leg_ik_bone_keys():
    """Normalized lookup keys for side-prefixed MMD knee/ankle bones."""
    keys = set()
    for stem in LEG_IK_BONE_STEMS:
        norm_stem = mmd_mapper._lookup_key(mmd_mapper._norm(stem))
        keys.add(norm_stem)
        for side in ("L", "R"):
            for variant in mmd_mapper._target_variants(stem, side):
                keys.add(mmd_mapper._lookup_key(variant))
    return keys


def _direct_thigh_targets(target):
    """Find MMD thigh bones by name when no BlendCap pair table is loaded."""
    lookup = {}
    for name in _bone_names(target):
        lookup.setdefault(mmd_mapper._lookup_key(name), name)
    found = []
    for side in ("L", "R"):
        name = mmd_mapper._find_target(THIGH_STEMS, side, lookup)
        if name is not None:
            found.append(name)
    return found


def _leg_ik_constraints(target):
    """IK constraints that drive the MMD knee/ankle leg chain."""
    found = []
    leg_bone_keys = _leg_ik_bone_keys()
    for pose_bone in target.pose.bones:
        for constraint in pose_bone.constraints:
            if constraint.type != "IK":
                continue
            bone_key = mmd_mapper._lookup_key(pose_bone.name)
            if bone_key in leg_bone_keys:
                found.append(constraint)
                continue
            target_key = mmd_mapper._lookup_key(
                getattr(constraint, "subtarget", "") or ""
            )
            if "ik" in target_key and any(
                marker in target_key for marker in LEG_IK_TARGET_MARKERS
            ):
                found.append(constraint)
    return found


def _foot_chain_set(target, thigh_targets):
    """Pose-bone names from each thigh down through the foot, inclusive."""
    children = {name: [] for name in _bone_names(target)}
    for name in _bone_names(target):
        parent = _bone_parents(target).get(name)
        if parent is not None:
            children.setdefault(parent, []).append(name)
    chain = set()
    queue = list(thigh_targets)
    while queue:
        cur = queue.pop()
        if cur in chain:
            continue
        chain.add(cur)
        queue.extend(children.get(cur, ()))
    return chain


def _restorable_leg_ik_constraints(target, thigh_targets):
    """IK constraints on the structural thigh-to-foot chain."""
    foot_chain = _foot_chain_set(target, thigh_targets)
    return [
        constraint
        for pose_bone in target.pose.bones
        if pose_bone.name in foot_chain
        for constraint in pose_bone.constraints
        if constraint.type == "IK"
    ]


def _leg_chain_transform_constraints(target, thigh_targets):
    """TRANSFORM constraints on the pelvis->thigh path that cancel FK yaw.

    MMD models such as 聖園ミカ put a 腰キャンセル bone between the pelvis
    and the thigh; its active TRANSFORM constraint counter-rotates the leg
    chain so feet stay facing forward. BlendCap cannot simulate TRANSFORM,
    so FK-Safe Apply disables these constraints during and after the bake.
    """
    parents = _bone_parents(target)
    protected = set()
    for thigh in thigh_targets:
        cur = thigh
        seen = set()
        while cur is not None and cur not in seen:
            protected.add(cur)
            seen.add(cur)
            cur = parents.get(cur)
    found = []
    for pose_bone in target.pose.bones:
        if pose_bone.name not in protected:
            continue
        for con in pose_bone.constraints:
            if con.type != "TRANSFORM":
                continue
            fingerprint = mmd_mapper._norm(
                " ".join((pose_bone.name, con.name, getattr(con, "subtarget", "") or ""))
            )
            if any(token in fingerprint for token in ("cancel", "キャンセル", "腰取消", "waist_cancel")):
                found.append(con)
    return found


class BCMB_OT_disable_leg_overrides(bpy.types.Operator):
    bl_idname = "blendcap_motion_bridge.disable_leg_overrides"
    bl_label = "Disable Leg Overrides"
    bl_description = (
        "Mute MMD leg IK and pelvis-to-thigh TRANSFORM cancel constraints "
        "after VMD import so FK thigh rotation from the VMD can drive the legs"
    )
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        target = getattr(context.scene, "blendcap_motion_bridge_vmd_target", None)
        if target is not None and target.type == "ARMATURE":
            return True
        active = context.active_object
        return active is not None and active.type == "ARMATURE"

    def execute(self, context):
        scene = context.scene
        target = getattr(scene, "blendcap_motion_bridge_vmd_target", None)
        if target is None and _blendcap_ready():
            target = scene.blendcap_retarget_target
        if target is None:
            active = context.active_object
            if active is not None and active.type == "ARMATURE":
                target = active
        if target is None or target.type != "ARMATURE":
            self.report({"ERROR"}, "Select the MMD armature first")
            return {"CANCELLED"}

        source = scene.blendcap_retarget_source if _blendcap_ready() else None
        thigh_targets = _best_thigh_targets(scene, source, target)
        if len(thigh_targets) < 2:
            self.report(
                {"ERROR"},
                "Could not find MMD thigh bones (足.L/足.R)",
            )
            return {"CANCELLED"}

        ik_constraints = _leg_ik_constraints(target)
        cancel_constraints = _leg_chain_transform_constraints(
            target, thigh_targets
        )
        disabled_ik = sum(
            1 for c in ik_constraints
            if not c.mute and c.influence > 1e-6
        )
        disabled_cancel = sum(
            1 for c in cancel_constraints
            if not c.mute and c.influence > 1e-6
        )
        for constraint in ik_constraints:
            constraint.mute = True
            constraint.influence = 0.0
        for constraint in cancel_constraints:
            constraint.mute = True
            constraint.influence = 0.0
        scene.blendcap_motion_bridge_vmd_ik_disabled = disabled_ik
        scene.blendcap_motion_bridge_vmd_cancel_disabled = disabled_cancel
        self.report(
            {"INFO"},
            f"Leg IK disabled: {disabled_ik}; leg cancel disabled: "
            f"{disabled_cancel}",
        )
        return {"FINISHED"}


class BCMB_OT_restore_leg_overrides(bpy.types.Operator):
    bl_idname = "blendcap_motion_bridge.restore_leg_overrides"
    bl_label = "Restore Leg IK"
    bl_description = (
        "Unmute the MMD knee/ankle IK constraints (足ＩＫ / つま先ＩＫ) "
        "so toe posing follows the ankle again after FK-Safe Apply or "
        "Disable Leg Overrides"
    )
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        target = getattr(context.scene, "blendcap_motion_bridge_vmd_target", None)
        if target is not None and target.type == "ARMATURE":
            return True
        active = context.active_object
        return active is not None and active.type == "ARMATURE"

    def execute(self, context):
        scene = context.scene
        target = getattr(scene, "blendcap_motion_bridge_vmd_target", None)
        if target is None and _blendcap_ready():
            target = scene.blendcap_retarget_target
        if target is None:
            active = context.active_object
            if active is not None and active.type == "ARMATURE":
                target = active
        if target is None or target.type != "ARMATURE":
            self.report({"ERROR"}, "Select the MMD armature first")
            return {"CANCELLED"}

        source = scene.blendcap_retarget_source if _blendcap_ready() else None
        thigh_targets = _best_thigh_targets(scene, source, target)
        if len(thigh_targets) < 2:
            self.report(
                {"ERROR"},
                "Could not find MMD thigh bones (足.L/足.R)",
            )
            return {"CANCELLED"}

        leg_ik = _restorable_leg_ik_constraints(target, thigh_targets)
        if not leg_ik:
            self.report(
                {"WARNING"},
                "No leg IK constraints found on this armature; "
                "nothing to restore",
            )
            return {"FINISHED"}

        restored = 0
        already_active = 0
        for constraint in leg_ik:
            if constraint.mute or constraint.influence <= 1e-6:
                constraint.mute = False
                constraint.influence = 1.0
                restored += 1
            else:
                already_active += 1

        scene.blendcap_motion_bridge_vmd_ik_disabled = max(
            0,
            scene.blendcap_motion_bridge_vmd_ik_disabled - restored,
        )
        if restored:
            message = (
                f"Restored {restored} leg IK constraint(s) to influence=1.0 "
                f"({already_active} already active); 腰キャンセル stays off"
            )
        else:
            message = (
                f"All {already_active} leg IK constraint(s) are already "
                "active (influence=1.0); 腰キャンセル stays off"
            )
        self.report({"INFO"}, message)
        return {"FINISHED"}


def _find_side_bone(target, stem, side):
    """Find a side bone like 足D.L via the mmd_mapper name variants."""
    lookup = {}
    for name in _bone_names(target):
        lookup.setdefault(mmd_mapper._lookup_key(name), name)
    return mmd_mapper._find_target((stem,), side, lookup)


# FK bone stem -> MMD additional-transform deform bone stem.
LEG_DEFORM_CHAIN = (
    ("足", "足D"),
    ("ひざ", "ひざD"),
    ("足首", "足首D"),
)


def _add_mmd_additional_rotation(pbone, subtarget):
    """Re-create the mmd_tools 'mmd_additional_rotation' TRANSFORM exactly.

    Baking (Bake Action / Bake Pose with constraints applied) removes this
    constraint from 足D/ひざD/足首D.  Re-adding it makes the deform chain
    follow the FK leg again so the toe follows the ankle when hand-keying.
    """
    import math

    con = pbone.constraints.new("TRANSFORM")
    con.name = "mmd_additional_rotation"
    con.target = pbone.id_data
    con.subtarget = subtarget
    con.map_from = "ROTATION"
    con.map_to = "ROTATION"
    con.map_to_x_from = "X"
    con.map_to_y_from = "Y"
    con.map_to_z_from = "Z"
    con.target_space = "LOCAL"
    con.owner_space = "LOCAL"
    con.mix_mode = "ADD"
    con.mix_mode_rot = "AFTER"
    con.from_rotation_mode = "XYZ"
    con.to_euler_order = "XYZ"
    con.use_motion_extrapolate = True
    for attr in ("from", "to"):
        for axis in ("x", "y", "z"):
            setattr(con, f"{attr}_min_{axis}", 0.0)
            setattr(con, f"{attr}_max_{axis}", 0.0)
            setattr(con, f"{attr}_min_{axis}_rot", -math.pi)
            setattr(con, f"{attr}_max_{axis}_rot", math.pi)
    con.influence = 1.0
    return con


def _matching_transform(pbone, subtarget):
    for con in pbone.constraints:
        if (
            con.type == "TRANSFORM"
            and con.subtarget == subtarget
        ):
            return con
    return None


def _relink_leg_deform_chain(target):
    """Re-add missing mmd_additional_rotation on the leg deform chain.

    Returns (added, already_active, missing_shadow).
    """
    added = 0
    already = 0
    missing_shadow = []
    for side in ("L", "R"):
        for _fk_stem, d_stem in LEG_DEFORM_CHAIN:
            d_name = _find_side_bone(target, d_stem, side)
            if d_name is None:
                continue
            pbone = target.pose.bones.get(d_name)
            if pbone is None:
                continue
            shadow = _find_side_bone(target, "_shadow_" + d_stem, side)
            if shadow is None:
                missing_shadow.append(d_name)
                continue
            existing = _matching_transform(pbone, shadow)
            if existing is not None:
                if not existing.mute and existing.influence > 0.5:
                    already += 1
                else:
                    existing.mute = False
                    existing.influence = 1.0
                    added += 1
                continue
            _add_mmd_additional_rotation(pbone, shadow)
            added += 1
    return added, already, missing_shadow


class BCMB_OT_relink_leg_deform(bpy.types.Operator):
    bl_idname = "blendcap_motion_bridge.relink_leg_deform"
    bl_label = "Re-link Leg Deform (After Bake)"
    bl_description = (
        "Re-add the MMD additional-transform constraints (足D/ひざD/足首D -> "
        "_shadow_<bone>) that Bake Action / Bake Pose removes, so the leg "
        "deform chain follows the FK leg again when hand-keying"
    )
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        target = getattr(context.scene, "blendcap_motion_bridge_vmd_target", None)
        if target is not None and target.type == "ARMATURE":
            return True
        active = context.active_object
        return active is not None and active.type == "ARMATURE"

    def execute(self, context):
        scene = context.scene
        target = getattr(scene, "blendcap_motion_bridge_vmd_target", None)
        if target is None and _blendcap_ready():
            target = scene.blendcap_retarget_target
        if target is None:
            active = context.active_object
            if active is not None and active.type == "ARMATURE":
                target = active
        if target is None or target.type != "ARMATURE":
            self.report({"ERROR"}, "Select the MMD armature first")
            return {"CANCELLED"}

        added, already, missing_shadow = _relink_leg_deform_chain(target)
        scene.blendcap_motion_bridge_vmd_deform_relinked = added
        if added:
            self.report(
                {"INFO"},
                f"Re-linked {added} leg deform constraint(s) "
                f"({already} already active); toe now follows the ankle",
            )
        elif already:
            self.report(
                {"INFO"},
                f"All {already} leg deform constraint(s) are already active; "
                "nothing to re-link",
            )
        elif missing_shadow:
            self.report(
                {"WARNING"},
                "No _shadow_ bones found to re-link "
                f"({', '.join(missing_shadow[:4])}); the MMD additional "
                "transform structure is missing on this armature",
            )
        else:
            self.report(
                {"WARNING"},
                "No leg deform chain (足D/ひざD/足首D) found on this armature",
            )
        return {"FINISHED"}




class BCMB_OT_detect(bpy.types.Operator):
    bl_idname = "blendcap_motion_bridge.detect"
    bl_label = "Detect Bone Mapping"
    bl_description = "Match BlendCap BVH bones to the MMD armature's bones"
    bl_options = {"REGISTER"}

    def execute(self, context):
        _source, _target, pairs, missing, error = _prepare_mapping(context, load_table=False)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        self.report({"INFO"}, f"已检查 {len(pairs)} 对；{len(missing)} 个可选项未匹配")
        return {"FINISHED"}


class BCMB_OT_auto_select(bpy.types.Operator):
    bl_idname = "blendcap_motion_bridge.auto_select"
    bl_label = "自动识别 BVH 与 MMD"
    bl_description = "只在来源与目标唯一且语义明确时自动选择；多个候选会停止并列出名称"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        source, target, error = _auto_select_rigs(context)
        if error:
            context.scene.blendcap_motion_bridge_status_level = "ERROR"
            context.scene.blendcap_motion_bridge_status = error
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        context.scene.blendcap_motion_bridge_status_level = "INFO"
        context.scene.blendcap_motion_bridge_status = f"已选择：{source.name} → {target.name}"
        self.report({"INFO"}, context.scene.blendcap_motion_bridge_status)
        return {"FINISHED"}


class BCMB_OT_prepare_in_memory(bpy.types.Operator):
    bl_idname = "blendcap_motion_bridge.prepare_in_memory"
    bl_label = "安全准备映射（不写盘）"
    bl_description = "验证传统 BVH profile 和 MMD 主链，再把映射载入 BlendCap 内存表；不会写 preset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        _source, _target, pairs, _missing, error = _prepare_mapping(context, load_table=True)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        self.report({"INFO"}, f"已安全载入 {len(pairs)} 对映射；未写 preset")
        return {"FINISHED"}


class BCMB_OT_write_preset(bpy.types.Operator):
    bl_idname = "blendcap_motion_bridge.write_preset"
    bl_label = "Write & Load Preset"
    bl_description = "Generate a BlendCap preset for the MMD rig and load it"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        source, target, pairs, missing, error = _prepare_mapping(context, load_table=False)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}

        source_prefix = mmd_mapper.detect_source_prefix(_bone_names(source), [p["source"] for p in pairs])
        try:
            path, backup = preset_writer.write_preset(
                target.name, pairs, source_prefix, return_backup=True
            )
        except (OSError, ValueError) as exc:
            scene.blendcap_motion_bridge_status_level = "ERROR"
            scene.blendcap_motion_bridge_status = f"preset 写入失败，旧文件保持不变：{exc}"
            self.report({"ERROR"}, scene.blendcap_motion_bridge_status)
            return {"CANCELLED"}
        _load_pairs_in_memory(scene, source, target, pairs)
        if not _table_matches(scene, pairs):
            scene.blendcap_motion_bridge_status_level = "ERROR"
            scene.blendcap_motion_bridge_status = "preset 写入后内存表校验失败"
            self.report({"ERROR"}, scene.blendcap_motion_bridge_status)
            return {"CANCELLED"}
        _authorize_mapping(scene, source, target, pairs)
        scene.blendcap_motion_bridge_last_preset = path
        scene.blendcap_motion_bridge_last_backup = backup
        scene.blendcap_motion_bridge_status_level = "READY"
        scene.blendcap_motion_bridge_status = f"已原子保存并校验 {len(pairs)} 对 preset"

        self.report({"INFO"}, scene.blendcap_motion_bridge_status)
        return {"FINISHED"}


class BCMB_OT_apply_face(bpy.types.Operator):
    bl_idname = "blendcap_motion_bridge.apply_face"
    bl_label = "Apply Face to MMD Shape Keys"
    bl_description = "Keyframe BlendCap ARKit face weights onto MMD shape keys"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        import numpy as np

        scene = context.scene
        npz_path = scene.blendcap_motion_bridge_face_npz.strip()
        if not npz_path or not os.path.isfile(npz_path):
            self.report({"ERROR"}, "Set an existing face NPZ file first")
            return {"CANCELLED"}

        obj = scene.blendcap_motion_bridge_face_mesh or context.active_object
        if obj is None or obj.type != "MESH" or obj.data.shape_keys is None:
            self.report(
                {"ERROR"},
                "Select or pick a mesh with shape keys first",
            )
            return {"CANCELLED"}

        try:
            face = np.load(npz_path, allow_pickle=False)
            blendshapes = face["face_blendshapes"]
            bs_names = [str(n) for n in face["blendshape_names"]]
        except Exception as exc:
            self.report({"ERROR"}, f"Could not read face NPZ: {exc}")
            return {"CANCELLED"}
        if blendshapes.ndim != 2 or len(blendshapes) == 0:
            self.report({"ERROR"}, "Face NPZ has no frame data")
            return {"CANCELLED"}

        sk_names = [sk.name for sk in obj.data.shape_keys.key_blocks]
        channels = face_mapper.build_face_channels(bs_names, sk_names)
        if not channels:
            self.report(
                {"ERROR"},
                "No ARKit or MMD shape keys matched",
            )
            return {"CANCELLED"}

        vals = face_mapper.compose_values(blendshapes, channels)
        n_frames = len(blendshapes)
        if "fps" in face:
            scene.render.fps = max(1, int(round(float(face["fps"]))))
        scene.frame_start = 1
        scene.frame_end = n_frames

        sk_data = obj.data.shape_keys
        if sk_data.animation_data is None:
            sk_data.animation_data_create()
        animation_data = sk_data.animation_data
        previous_action = animation_data.action
        previous_slot = _action_slot(animation_data)
        previous_use_nla = bool(animation_data.use_nla)
        if previous_action is not None:
            previous_action.use_fake_user = True
        action = bpy.data.actions.new(name=f"ACT_{obj.name}_MMD_Face")
        action.use_fake_user = True
        action["blendcap_motion_bridge_role"] = "FACE_OUTPUT"
        action["blendcap_motion_bridge_source_npz"] = os.path.basename(npz_path)
        key_slot = action.slots.new(id_type="KEY", name=obj.name)
        animation_data.action = action
        animation_data.use_nla = False
        try:
            action.slots.active = key_slot
        except Exception:
            key_slot.active = True
        sk_data.animation_data.action_slot = key_slot
        fcurves = _ensure_fcurve_collection(action, key_slot)
        frames = np.arange(1, n_frames + 1, dtype=np.float64)
        linear = 1
        try:
            for col, channel in enumerate(channels):
                path = obj.data.shape_keys.key_blocks[
                    channel.target
                ].path_from_id("value")
                fc = fcurves.find(path)
                if fc is None:
                    fc = fcurves.new(path)
                pts = fc.keyframe_points
                pts.add(n_frames)
                co = np.empty(n_frames * 2, dtype=np.float64)
                co[0::2] = frames
                co[1::2] = vals[:, col]
                pts.foreach_set("co", co)
                pts.foreach_set(
                    "interpolation",
                    np.full(n_frames, linear, dtype=np.int32),
                )
                fc.update()
        except Exception as exc:
            _bind_action(animation_data, previous_action, previous_slot)
            animation_data.use_nla = previous_use_nla
            action.use_fake_user = False
            if action.users == 0:
                bpy.data.actions.remove(action)
            self.report({"ERROR"}, f"表情 Action 创建失败；原动画已恢复：{exc}")
            return {"CANCELLED"}

        scene.blendcap_motion_bridge_face_matched = len(channels)
        scene.blendcap_motion_bridge_face_total = len(bs_names)
        self.report(
            {"INFO"},
            f"Applied {len(channels)}/{len(bs_names)} face channels "
            f"across {n_frames} frames",
        )
        return {"FINISHED"}


def _action_slot(animation_data):
    if not hasattr(animation_data, "action_slot"):
        return None
    try:
        return animation_data.action_slot
    except (AttributeError, RuntimeError):
        return None


def _slot_identifier(slot):
    try:
        return str(slot.identifier) if slot is not None else ""
    except (AttributeError, ReferenceError, RuntimeError):
        return ""


def _find_slot(action, identifier):
    if action is None or not identifier:
        return None
    return next(
        (slot for slot in getattr(action, "slots", ()) if _slot_identifier(slot) == identifier),
        None,
    )


def _bind_action(animation_data, action, preferred_slot=None):
    animation_data.action = action
    if action is None or not hasattr(animation_data, "action_slot"):
        return
    if preferred_slot is not None:
        try:
            animation_data.action_slot = preferred_slot
            return
        except (AttributeError, RuntimeError, TypeError):
            pass
    suitable = list(getattr(animation_data, "action_suitable_slots", ()) or ())
    if suitable:
        try:
            animation_data.action_slot = suitable[0]
        except (AttributeError, RuntimeError, TypeError):
            pass


_POSE_CHANNELS = (
    "location",
    "rotation_euler",
    "rotation_quaternion",
    "rotation_axis_angle",
    "scale",
)
_REST_VALUES = {
    "location": (0.0, 0.0, 0.0),
    "rotation_euler": (0.0, 0.0, 0.0),
    "rotation_quaternion": (1.0, 0.0, 0.0, 0.0),
    "rotation_axis_angle": (0.0, 0.0, 1.0, 0.0),
    "scale": (1.0, 1.0, 1.0),
}
_PREROLL_START_MARKER = "BCMB_PRE_ROLL_START"
_MOTION_START_MARKER = "BCMB_MOTION_START"


def _capture_pose_channels(target, rest_pose=False):
    """Capture transform-channel values addressable by an Action F-Curve."""
    values = {
        "location": tuple(float(value) for value in target.location),
        "rotation_euler": tuple(float(value) for value in target.rotation_euler),
        "rotation_quaternion": tuple(float(value) for value in target.rotation_quaternion),
        "rotation_axis_angle": tuple(float(value) for value in target.rotation_axis_angle),
        "scale": tuple(float(value) for value in target.scale),
    }
    for pose_bone in target.pose.bones:
        for prop_name in _POSE_CHANNELS:
            path = pose_bone.path_from_id(prop_name)
            source = _REST_VALUES[prop_name] if rest_pose else getattr(pose_bone, prop_name)
            values[path] = tuple(float(value) for value in source)
    return values


def _sample_preroll_pose(context, target):
    scene = context.scene
    source = scene.blendcap_motion_bridge_preroll_pose_source
    if source == "REST":
        return _capture_pose_channels(target, rest_pose=True)
    if source == "CURRENT":
        context.view_layer.update()
        return _capture_pose_channels(target)
    action = scene.blendcap_motion_bridge_preroll_pose_action
    if action is None:
        raise RuntimeError("初始姿态来源为 Action 时必须选择姿态 Action")

    animation_data = target.animation_data_create()
    previous_action = animation_data.action
    previous_slot = _action_slot(animation_data)
    previous_use_nla = bool(animation_data.use_nla)
    previous_frame = scene.frame_current
    try:
        _bind_action(animation_data, action)
        animation_data.use_nla = False
        scene.frame_set(scene.blendcap_motion_bridge_preroll_pose_frame)
        context.view_layer.update()
        return _capture_pose_channels(target)
    finally:
        _bind_action(animation_data, previous_action, previous_slot)
        animation_data.use_nla = previous_use_nla
        scene.frame_set(previous_frame)
        context.view_layer.update()


def _action_channelbags(action, slot=None):
    bags = []
    slot_handle = getattr(slot, "handle", None) if slot is not None else None
    for layer in getattr(action, "layers", ()) or ():
        for strip in getattr(layer, "strips", ()) or ():
            if getattr(strip, "type", "") != "KEYFRAME":
                continue
            for channelbag in getattr(strip, "channelbags", ()) or ():
                if (
                    slot_handle is None
                    or getattr(channelbag, "slot_handle", None) == slot_handle
                ):
                    bags.append(channelbag)
    return tuple(bags)


def _action_fcurves(action, slot=None):
    legacy_fcurves = getattr(action, "fcurves", None)
    if legacy_fcurves is not None:
        return tuple(legacy_fcurves)
    return tuple(
        fcurve
        for channelbag in _action_channelbags(action, slot)
        for fcurve in channelbag.fcurves
    )


def _ensure_fcurve_collection(action, slot=None):
    legacy_fcurves = getattr(action, "fcurves", None)
    if legacy_fcurves is not None:
        return legacy_fcurves
    if slot is None:
        try:
            slot = action.slots.active
        except (AttributeError, RuntimeError):
            slot = next(iter(getattr(action, "slots", ()) or ()), None)
    if slot is None:
        raise RuntimeError("分层 Action 没有可写入的 Slot")
    channelbags = _action_channelbags(action, slot)
    if channelbags:
        return channelbags[0].fcurves
    layers = getattr(action, "layers", None)
    if layers is None:
        raise RuntimeError("Action 不支持 F-Curve 或 Layer")
    layer = next(iter(layers), None)
    if layer is None:
        layer = layers.new("BCMB Layer")
    strip = next(
        (
            item
            for item in getattr(layer, "strips", ()) or ()
            if getattr(item, "type", "") == "KEYFRAME"
        ),
        None,
    )
    if strip is None:
        strip = layer.strips.new(type="KEYFRAME")
    return strip.channelbags.new(slot).fcurves


def _action_first_frame(action, slot=None):
    frames = [
        float(point.co.x)
        for fcurve in _action_fcurves(action, slot)
        for point in fcurve.keyframe_points
    ]
    if not frames:
        raise RuntimeError("BlendCap 输出 Action 没有关键帧，无法建立起始缓冲")
    return int(round(min(frames)))


def _keyframe_at(fcurve, frame):
    return next(
        (
            point
            for point in fcurve.keyframe_points
            if abs(float(point.co.x) - float(frame)) <= 1e-4
        ),
        None,
    )


def _set_fcurve_key(fcurve, frame, value, interpolation="BEZIER"):
    point = _keyframe_at(fcurve, frame)
    if point is None:
        point = fcurve.keyframe_points.insert(float(frame), float(value), options={"FAST"})
    else:
        point.co.y = float(value)
    point.interpolation = interpolation
    if interpolation == "BEZIER":
        point.handle_left_type = "AUTO_CLAMPED"
        point.handle_right_type = "AUTO_CLAMPED"
    return point


def _set_timeline_marker(scene, name, frame):
    marker = scene.timeline_markers.get(name)
    if marker is None:
        marker = scene.timeline_markers.new(name, frame=int(frame))
    else:
        marker.frame = int(frame)


def _remove_timeline_marker(scene, name):
    marker = scene.timeline_markers.get(name)
    if marker is not None:
        scene.timeline_markers.remove(marker)


def _rigid_body_point_cache(scene):
    world = getattr(scene, "rigidbody_world", None)
    return getattr(world, "point_cache", None) if world is not None else None


def _check_preroll_cache(scene):
    cache = _rigid_body_point_cache(scene)
    if cache is not None and cache.is_baked:
        raise RuntimeError("刚体缓存已烘焙；请先删除现有物理烘焙再执行带起始缓冲的重定向")


def _apply_preroll(scene, target, action, snapshot):
    hold = int(scene.blendcap_motion_bridge_preroll_hold_frames)
    transition = int(scene.blendcap_motion_bridge_preroll_transition_frames)
    total = hold + transition
    if not scene.blendcap_motion_bridge_preroll_enabled or total <= 0:
        return None

    animation_data = target.animation_data
    slot = _action_slot(animation_data) if animation_data is not None else None
    motion_start = _action_first_frame(action, slot)
    preroll_start = motion_start - total
    fcurves = _action_fcurves(action, slot)
    first_values = {
        (fcurve.data_path, int(fcurve.array_index)): float(fcurve.evaluate(motion_start))
        for fcurve in fcurves
    }
    transition_start = motion_start - transition
    for fcurve in fcurves:
        key = (fcurve.data_path, int(fcurve.array_index))
        channel_values = snapshot.get(fcurve.data_path)
        if channel_values is not None and int(fcurve.array_index) < len(channel_values):
            initial_value = float(channel_values[int(fcurve.array_index)])
        else:
            initial_value = first_values[key]

        start_interpolation = "CONSTANT" if hold > 0 else "BEZIER"
        _set_fcurve_key(fcurve, preroll_start, initial_value, start_interpolation)
        if hold > 0:
            hold_end = transition_start if transition > 0 else motion_start - 1
            hold_interpolation = "BEZIER" if transition > 0 else "CONSTANT"
            _set_fcurve_key(fcurve, hold_end, initial_value, hold_interpolation)
        motion_point = _keyframe_at(fcurve, motion_start)
        if motion_point is None:
            _set_fcurve_key(
                fcurve, motion_start, first_values[key], "CONSTANT"
            )
        else:
            motion_point.co.y = first_values[key]
        fcurve.update()

    cache = _rigid_body_point_cache(scene)
    previous_cache_start = int(cache.frame_start) if cache is not None else motion_start
    if cache is not None:
        cache.frame_start = preroll_start

    action["blendcap_motion_bridge_preroll_pending"] = True
    action["blendcap_motion_bridge_preroll_start"] = preroll_start
    action["blendcap_motion_bridge_motion_start"] = motion_start
    action["blendcap_motion_bridge_preroll_hold_frames"] = hold
    action["blendcap_motion_bridge_preroll_transition_frames"] = transition
    scene.blendcap_motion_bridge_preroll_pending = True
    scene.blendcap_motion_bridge_preroll_start = preroll_start
    scene.blendcap_motion_bridge_preroll_motion_start = motion_start
    scene.blendcap_motion_bridge_preroll_target = target
    scene.blendcap_motion_bridge_preroll_action = action
    scene.blendcap_motion_bridge_preroll_simulated = False
    scene.blendcap_motion_bridge_preroll_cleanup_confirmed = False
    scene.blendcap_motion_bridge_preroll_previous_cache_start = previous_cache_start
    _set_timeline_marker(scene, _PREROLL_START_MARKER, preroll_start)
    _set_timeline_marker(scene, _MOTION_START_MARKER, motion_start)
    return preroll_start, motion_start


def _clear_preroll_state(scene, restore_unbaked_cache=False):
    cache = _rigid_body_point_cache(scene)
    if (
        restore_unbaked_cache
        and cache is not None
        and not cache.is_baked
    ):
        cache.frame_start = scene.blendcap_motion_bridge_preroll_previous_cache_start
    _remove_timeline_marker(scene, _PREROLL_START_MARKER)
    _remove_timeline_marker(scene, _MOTION_START_MARKER)
    scene.blendcap_motion_bridge_preroll_pending = False
    scene.blendcap_motion_bridge_preroll_target = None
    scene.blendcap_motion_bridge_preroll_action = None
    scene.blendcap_motion_bridge_preroll_simulated = False
    scene.blendcap_motion_bridge_preroll_cleanup_confirmed = False


def _delete_keys_before(action, frame, slot=None):
    removed = 0
    for fcurve in _action_fcurves(action, slot):
        while True:
            point = next(
                (
                    item
                    for item in fcurve.keyframe_points
                    if float(item.co.x) < float(frame) - 1e-4
                ),
                None,
            )
            if point is None:
                break
            fcurve.keyframe_points.remove(point, fast=True)
            removed += 1
        fcurve.update()
    return removed


def _constraint_rows(target, constraints):
    pointers = {constraint.as_pointer() for constraint in constraints}
    rows = []
    for pose_bone in target.pose.bones:
        for constraint in pose_bone.constraints:
            if constraint.as_pointer() not in pointers:
                continue
            rows.append({
                "owner": pose_bone.name,
                "name": constraint.name,
                "type": constraint.type,
                "mute": bool(constraint.mute),
                "influence": float(constraint.influence),
            })
    return rows


def _restore_constraint_rows(target, rows):
    restored = 0
    missing = []
    for row in rows:
        pose_bone = target.pose.bones.get(row.get("owner", ""))
        constraint = pose_bone.constraints.get(row.get("name", "")) if pose_bone else None
        if constraint is None or constraint.type != row.get("type"):
            missing.append(f"{row.get('owner')}::{row.get('name')}")
            continue
        constraint.mute = bool(row["mute"])
        constraint.influence = float(row["influence"])
        restored += 1
    return restored, missing


def _restore_saved_constraint_snapshot(scene):
    if not scene.blendcap_motion_bridge_constraint_snapshot:
        return 0, []
    try:
        rows = json.loads(scene.blendcap_motion_bridge_constraint_snapshot)
        target = scene.blendcap_motion_bridge_constraint_target
    except (json.JSONDecodeError, ReferenceError):
        return 0, ["快照或目标无效"]
    if target is None or target.type != "ARMATURE" or not isinstance(rows, list):
        return 0, ["快照或目标无效"]
    restored, missing = _restore_constraint_rows(target, rows)
    if not missing:
        scene.blendcap_motion_bridge_constraint_snapshot = ""
        scene.blendcap_motion_bridge_constraint_target = None
    return restored, missing


def _safe_action_name(value):
    return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in value)[:48] or "MMD"


class BCMB_OT_apply_retarget_fk_safe(bpy.types.Operator):
    bl_idname = "blendcap_motion_bridge.apply_retarget_fk_safe"
    bl_label = "FK-Safe Apply (MMD)"
    bl_description = (
        "Apply BlendCap retargeting with MMD IK and pelvis-to-thigh "
        "cancel constraints temporarily muted so FK thigh keys are not "
        "overridden; active constraints are left disabled after the bake"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not _blendcap_ready():
            return False
        scene = context.scene
        return (
            scene.blendcap_retarget_source is not None
            and scene.blendcap_retarget_target is not None
        )

    def execute(self, context):
        scene = context.scene
        source, target, pairs, _missing, error = _prepare_mapping(context, load_table=False)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        expected_signature = _mapping_signature(source, target, pairs)
        if (
            scene.blendcap_motion_bridge_mapping_source_object != source
            or scene.blendcap_motion_bridge_mapping_target_object != target
            or scene.blendcap_motion_bridge_mapping_source != source.name
            or scene.blendcap_motion_bridge_mapping_target != target.name
            or scene.blendcap_motion_bridge_mapping_signature != expected_signature
        ):
            scene.blendcap_motion_bridge_status_level = "ERROR"
            scene.blendcap_motion_bridge_status = (
                "当前映射未授权给所选 BVH/MMD 对象；请先点“安全准备映射”"
            )
            self.report({"ERROR"}, scene.blendcap_motion_bridge_status)
            return {"CANCELLED"}
        if not _table_matches(scene, pairs):
            scene.blendcap_motion_bridge_status_level = "ERROR"
            scene.blendcap_motion_bridge_status = "当前 BlendCap pair table 不属于所选 BVH/MMD；请先点“安全准备映射”"
            self.report({"ERROR"}, scene.blendcap_motion_bridge_status)
            return {"CANCELLED"}
        if scene.blendcap_motion_bridge_preroll_pending:
            scene.blendcap_motion_bridge_status_level = "ERROR"
            scene.blendcap_motion_bridge_status = "已有未清理的预滚动区；请先烘焙并清理，或恢复原状态"
            self.report({"ERROR"}, scene.blendcap_motion_bridge_status)
            return {"CANCELLED"}
        if scene.blendcap_motion_bridge_previous_state_available:
            try:
                baseline_target = scene.blendcap_motion_bridge_previous_target
            except ReferenceError:
                baseline_target = None
            if baseline_target is not None and baseline_target != target:
                scene.blendcap_motion_bridge_status_level = "ERROR"
                scene.blendcap_motion_bridge_status = "已有另一角色的恢复基线；请先恢复原状态"
                self.report({"ERROR"}, scene.blendcap_motion_bridge_status)
                return {"CANCELLED"}

        _restored, restore_missing = _restore_saved_constraint_snapshot(scene)
        if restore_missing:
            scene.blendcap_motion_bridge_status_level = "ERROR"
            scene.blendcap_motion_bridge_status = f"上次约束快照不完整：{'、'.join(restore_missing[:4])}"
            self.report({"ERROR"}, scene.blendcap_motion_bridge_status)
            return {"CANCELLED"}

        preroll_snapshot = None
        if (
            scene.blendcap_motion_bridge_preroll_enabled
            and (
                scene.blendcap_motion_bridge_preroll_hold_frames
                + scene.blendcap_motion_bridge_preroll_transition_frames
            ) > 0
        ):
            try:
                _check_preroll_cache(scene)
                preroll_snapshot = _sample_preroll_pose(context, target)
            except Exception as exc:
                scene.blendcap_motion_bridge_status_level = "ERROR"
                scene.blendcap_motion_bridge_status = f"起始缓冲准备失败：{exc}"
                self.report({"ERROR"}, scene.blendcap_motion_bridge_status)
                return {"CANCELLED"}

        thigh_targets = _thigh_targets(scene, source, target)
        ik_constraints = _leg_ik_constraints(target)
        cancel_constraints = _leg_chain_transform_constraints(target, thigh_targets)
        selected = []
        seen = set()
        for constraint in (*ik_constraints, *cancel_constraints):
            pointer = constraint.as_pointer()
            if pointer not in seen:
                seen.add(pointer)
                selected.append(constraint)
        snapshot_rows = _constraint_rows(target, selected)
        disabled_ik = sum(
            1 for constraint in ik_constraints
            if not constraint.mute and constraint.influence > 1e-6
        )
        disabled_cancel = sum(
            1 for constraint in cancel_constraints
            if not constraint.mute and constraint.influence > 1e-6
        )
        for constraint in selected:
            constraint.mute = True
            constraint.influence = 0.0

        animation_data = target.animation_data_create()
        previous_action = animation_data.action
        previous_slot = _action_slot(animation_data)
        previous_slot_id = _slot_identifier(previous_slot)
        previous_use_nla = bool(animation_data.use_nla)
        previous_fake_user = bool(previous_action.use_fake_user) if previous_action else False
        if previous_action is not None:
            previous_action.use_fake_user = True
        before_actions = {action.as_pointer() for action in bpy.data.actions}
        _bind_action(animation_data, None)
        animation_data.use_nla = False

        auto_bake_ik = scene.blendcap_retarget_auto_bake_ik
        scene.blendcap_retarget_auto_bake_ik = False
        result = {"CANCELLED"}
        failure = ""
        created_action = None
        try:
            result = bpy.ops.blendcap.apply_retarget()
            created_action = animation_data.action
            if result != {"FINISHED"} or created_action is None:
                raise RuntimeError(f"BlendCap retarget 未完成：{result}")
            created_action.name = f"ACT_{_safe_action_name(target.name)}_BlendCap_Motion_Bridge"
            created_action.use_fake_user = True
            created_action["blendcap_motion_bridge_role"] = "RETARGET_OUTPUT"
            created_action["blendcap_motion_bridge_source"] = source.name
            created_action["blendcap_motion_bridge_target"] = target.name
            created_action["blendcap_motion_bridge_mapping_signature"] = scene.blendcap_motion_bridge_mapping_signature
            if preroll_snapshot is not None:
                preroll_range = _apply_preroll(
                    scene, target, created_action, preroll_snapshot
                )
                if preroll_range is not None:
                    preroll_result = bpy.ops.blendcap_motion_bridge.run_preroll(
                        "EXEC_DEFAULT"
                    )
                    if preroll_result != {"FINISHED"}:
                        raise RuntimeError(f"负帧预滚动未完成：{preroll_result}")
        except Exception as exc:
            failure = str(exc)
            if scene.blendcap_motion_bridge_preroll_pending:
                _clear_preroll_state(scene, restore_unbaked_cache=True)
            _restore_constraint_rows(target, snapshot_rows)
            failed_action = animation_data.action
            try:
                _bind_action(animation_data, previous_action, previous_slot)
                animation_data.use_nla = previous_use_nla
            except (AttributeError, RuntimeError, TypeError):
                pass
            if previous_action is not None:
                previous_action.use_fake_user = previous_fake_user
            if (
                failed_action is not None
                and failed_action != previous_action
                and failed_action.as_pointer() not in before_actions
            ):
                failed_action.use_fake_user = False
                if failed_action.users == 0:
                    bpy.data.actions.remove(failed_action)
        finally:
            scene.blendcap_retarget_auto_bake_ik = auto_bake_ik

        if failure:
            scene.blendcap_motion_bridge_status_level = "ERROR"
            scene.blendcap_motion_bridge_status = f"重定向失败；原动作和约束已恢复：{failure}"
            self.report({"ERROR"}, scene.blendcap_motion_bridge_status)
            return {"CANCELLED"}

        scene.blendcap_motion_bridge_ik_protected = disabled_ik
        scene.blendcap_motion_bridge_cancel_protected = disabled_cancel
        scene.blendcap_motion_bridge_constraint_snapshot = json.dumps(snapshot_rows, ensure_ascii=False)
        scene.blendcap_motion_bridge_constraint_target = target
        if not scene.blendcap_motion_bridge_previous_state_available:
            scene.blendcap_motion_bridge_previous_state_available = True
            scene.blendcap_motion_bridge_previous_target = target
            scene.blendcap_motion_bridge_previous_action = previous_action
            scene.blendcap_motion_bridge_previous_action_name = previous_action.name if previous_action else ""
            scene.blendcap_motion_bridge_previous_action_slot = previous_slot_id
            scene.blendcap_motion_bridge_previous_use_nla = previous_use_nla
            scene.blendcap_motion_bridge_previous_action_fake_user = previous_fake_user
        scene.blendcap_motion_bridge_last_output_action = created_action.name
        scene.blendcap_motion_bridge_status_level = "READY"
        if scene.blendcap_motion_bridge_preroll_pending:
            buffer_note = (
                f"；预滚动 {scene.blendcap_motion_bridge_preroll_start}"
                f"～{scene.blendcap_motion_bridge_preroll_motion_start - 1}，"
                f"正式动作从 {scene.blendcap_motion_bridge_preroll_motion_start} 开始"
            )
        else:
            buffer_note = ""
        scene.blendcap_motion_bridge_status = (
            f"完成：{created_action.name}；仅关闭 {disabled_ik} 个腿 IK、"
            f"{disabled_cancel} 个腰取消约束{buffer_note}"
        )
        self.report({"INFO"}, scene.blendcap_motion_bridge_status)
        return {"FINISHED"}


class BCMB_OT_quick_retarget(bpy.types.Operator):
    bl_idname = "blendcap_motion_bridge.quick_retarget"
    bl_label = "自动准备并安全重定向"
    bl_description = "自动识别传统 BVH/MMD、在内存中载入经过验证的映射，再创建独立输出 Action；不写 preset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        if not _blendcap_ready():
            self.report({"ERROR"}, "BlendCap 未启用")
            return {"CANCELLED"}
        previous_table = _capture_table_state(scene)
        new_table_snapshot = not bool(scene.blendcap_motion_bridge_previous_table_json)
        if new_table_snapshot:
            scene.blendcap_motion_bridge_previous_table_json = _table_state_json(previous_table)
        _source, _target, _pairs, _missing, error = _prepare_mapping(context, load_table=True)
        if error:
            if new_table_snapshot:
                scene.blendcap_motion_bridge_previous_table_json = ""
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        try:
            result = bpy.ops.blendcap_motion_bridge.apply_retarget_fk_safe("EXEC_DEFAULT")
        except (AttributeError, RuntimeError) as exc:
            _restore_table_state(scene, previous_table)
            if new_table_snapshot:
                scene.blendcap_motion_bridge_previous_table_json = ""
            scene.blendcap_motion_bridge_status_level = "ERROR"
            scene.blendcap_motion_bridge_status = f"一键重定向失败，旧映射已恢复：{exc}"
            self.report({"ERROR"}, scene.blendcap_motion_bridge_status)
            return {"CANCELLED"}
        if result != {"FINISHED"}:
            _restore_table_state(scene, previous_table)
            if new_table_snapshot:
                scene.blendcap_motion_bridge_previous_table_json = ""
            self.report({"ERROR"}, "一键重定向未完成；旧 BlendCap 映射已恢复")
            return {"CANCELLED"}
        return {"FINISHED"}


class BCMB_OT_run_preroll(bpy.types.Operator):
    bl_idname = "blendcap_motion_bridge.run_preroll"
    bl_label = "运行负帧预滚动"
    bl_description = "从记录的负帧起点逐帧求值到真实动作首帧，让裙发物理获得稳定初态"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return bool(context.scene.blendcap_motion_bridge_preroll_pending)

    def execute(self, context):
        scene = context.scene
        start = int(scene.blendcap_motion_bridge_preroll_start)
        motion_start = int(scene.blendcap_motion_bridge_preroll_motion_start)
        target = scene.blendcap_motion_bridge_preroll_target
        if target is None or target.type != "ARMATURE":
            self.report({"ERROR"}, "预滚动目标骨架已不存在")
            return {"CANCELLED"}
        if start >= motion_start:
            self.report({"ERROR"}, "记录的预滚动范围无效")
            return {"CANCELLED"}

        cache = _rigid_body_point_cache(scene)
        if cache is not None:
            if cache.is_baked:
                if int(cache.frame_start) > start:
                    self.report({"ERROR"}, "当前刚体烘焙未包含完整负帧区；请删除烘焙后重新运行")
                    return {"CANCELLED"}
                scene.blendcap_motion_bridge_preroll_simulated = True
                scene.frame_set(motion_start)
                self.report({"INFO"}, "刚体缓存已包含预滚动区，无需重复运行")
                return {"FINISHED"}
            cache.frame_start = start

        total = motion_start - start + 1
        wm = context.window_manager
        wm.progress_begin(0, total)
        try:
            for index, frame in enumerate(range(start, motion_start + 1)):
                scene.frame_set(frame)
                context.view_layer.update()
                wm.progress_update(index + 1)
        finally:
            wm.progress_end()
        scene.frame_set(motion_start)
        scene.blendcap_motion_bridge_preroll_simulated = True
        scene.blendcap_motion_bridge_status_level = "READY"
        scene.blendcap_motion_bridge_status = (
            f"预滚动已求值：{start}～{motion_start - 1}；"
            f"真实动作首帧 {motion_start} 保持不变"
        )
        self.report({"INFO"}, scene.blendcap_motion_bridge_status)
        return {"FINISHED"}


class BCMB_OT_cleanup_preroll(bpy.types.Operator):
    bl_idname = "blendcap_motion_bridge.cleanup_preroll"
    bl_label = "完成并清理预滚动"
    bl_description = "物理烘焙完成后删除真实动作首帧之前的键；不会移动正式动作"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(context.scene.blendcap_motion_bridge_preroll_pending)

    def execute(self, context):
        scene = context.scene
        if not scene.blendcap_motion_bridge_preroll_cleanup_confirmed:
            self.report({"ERROR"}, "请先完成裙发物理烘焙，并勾选确认项")
            return {"CANCELLED"}
        try:
            target = scene.blendcap_motion_bridge_preroll_target
        except ReferenceError:
            target = None
        if target is None or target.type != "ARMATURE":
            self.report({"ERROR"}, "预滚动目标骨架已不存在")
            return {"CANCELLED"}
        animation_data = target.animation_data
        action = animation_data.action if animation_data is not None else None
        try:
            recorded_action = scene.blendcap_motion_bridge_preroll_action
        except ReferenceError:
            recorded_action = None
        actions = []
        for candidate in (action, recorded_action):
            if candidate is not None and candidate not in actions:
                actions.append(candidate)
        if not actions:
            self.report({"ERROR"}, "没有可清理的目标 Action")
            return {"CANCELLED"}

        motion_start = int(scene.blendcap_motion_bridge_preroll_motion_start)
        active_slot = _action_slot(animation_data) if animation_data is not None else None
        removed = 0
        for candidate in actions:
            slot = active_slot if candidate == action else None
            removed += _delete_keys_before(candidate, motion_start, slot)
            for key in (
                "blendcap_motion_bridge_preroll_pending",
                "blendcap_motion_bridge_preroll_start",
                "blendcap_motion_bridge_motion_start",
                "blendcap_motion_bridge_preroll_hold_frames",
                "blendcap_motion_bridge_preroll_transition_frames",
            ):
                if key in candidate:
                    del candidate[key]
            candidate["blendcap_motion_bridge_preroll_cleaned"] = True
        _clear_preroll_state(scene, restore_unbaked_cache=True)
        scene.frame_set(motion_start)
        scene.blendcap_motion_bridge_status_level = "READY"
        scene.blendcap_motion_bridge_status = (
            f"已删除 {removed} 个预滚动关键帧；正式动作仍从第 {motion_start} 帧开始"
        )
        self.report({"INFO"}, scene.blendcap_motion_bridge_status)
        return {"FINISHED"}


class BCMB_OT_restore_previous_state(bpy.types.Operator):
    bl_idname = "blendcap_motion_bridge.restore_previous_state"
    bl_label = "恢复重定向前角色状态"
    bl_description = "精确恢复腿链约束和目标 Action/NLA；生成的输出 Action 保留"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        scene = context.scene
        return bool(
            scene.blendcap_motion_bridge_constraint_snapshot
            or scene.blendcap_motion_bridge_previous_state_available
            or scene.blendcap_motion_bridge_previous_table_json
        )

    def execute(self, context):
        scene = context.scene
        restored, missing = _restore_saved_constraint_snapshot(scene)
        if missing:
            scene.blendcap_motion_bridge_status_level = "ERROR"
            scene.blendcap_motion_bridge_status = f"约束恢复不完整：{'、'.join(missing[:4])}"
            self.report({"ERROR"}, scene.blendcap_motion_bridge_status)
            return {"CANCELLED"}
        if scene.blendcap_motion_bridge_previous_state_available:
            try:
                target = scene.blendcap_motion_bridge_previous_target
            except ReferenceError:
                target = None
            action = scene.blendcap_motion_bridge_previous_action
            if action is None and scene.blendcap_motion_bridge_previous_action_name:
                action = bpy.data.actions.get(scene.blendcap_motion_bridge_previous_action_name)
            if target is None or target.type != "ARMATURE":
                self.report({"ERROR"}, "之前的目标骨架已不存在")
                return {"CANCELLED"}
            if action is None and scene.blendcap_motion_bridge_previous_action_name:
                self.report({"ERROR"}, "之前的目标 Action 已不存在")
                return {"CANCELLED"}
            animation_data = target.animation_data_create()
            current = animation_data.action
            if current is not None and current != action:
                current.use_fake_user = True
            _bind_action(animation_data, action, _find_slot(action, scene.blendcap_motion_bridge_previous_action_slot))
            animation_data.use_nla = scene.blendcap_motion_bridge_previous_use_nla
            if action is not None:
                action.use_fake_user = scene.blendcap_motion_bridge_previous_action_fake_user
            scene.blendcap_motion_bridge_previous_state_available = False
            scene.blendcap_motion_bridge_previous_target = None
            scene.blendcap_motion_bridge_previous_action = None
            scene.blendcap_motion_bridge_previous_action_name = ""
            scene.blendcap_motion_bridge_previous_action_slot = ""
        if scene.blendcap_motion_bridge_previous_table_json:
            try:
                table_state = _table_state_from_json(scene.blendcap_motion_bridge_previous_table_json)
                _restore_table_state(scene, table_state)
            except (json.JSONDecodeError, ValueError) as exc:
                scene.blendcap_motion_bridge_status_level = "ERROR"
                scene.blendcap_motion_bridge_status = f"旧 BlendCap 映射恢复失败：{exc}"
                self.report({"ERROR"}, scene.blendcap_motion_bridge_status)
                return {"CANCELLED"}
            scene.blendcap_motion_bridge_previous_table_json = ""
        if scene.blendcap_motion_bridge_preroll_pending:
            _clear_preroll_state(scene, restore_unbaked_cache=True)
        scene.blendcap_motion_bridge_status_level = "READY"
        scene.blendcap_motion_bridge_status = f"已恢复重定向前角色状态和 {restored} 个约束；输出 Action 保留"
        self.report({"INFO"}, scene.blendcap_motion_bridge_status)
        return {"FINISHED"}


CLASSES = (
    BCMB_OT_relink_leg_deform,
    BCMB_OT_auto_select,
    BCMB_OT_detect,
    BCMB_OT_prepare_in_memory,
    BCMB_OT_write_preset,
    BCMB_OT_disable_leg_overrides,
    BCMB_OT_restore_leg_overrides,
    BCMB_OT_apply_retarget_fk_safe,
    BCMB_OT_quick_retarget,
    BCMB_OT_run_preroll,
    BCMB_OT_cleanup_preroll,
    BCMB_OT_restore_previous_state,
    BCMB_OT_apply_face,
)
