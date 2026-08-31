"""Deterministic MMD bone -> BlendCap source bone mapping.

BlendCap's retarget presets store pairs as
{"source": <BlendCap BVH bone>, "target": <rig bone>, ...}.  MMD rigs do
not share a namespace with BlendCap, so Auto-Match cannot fill the table.
This module maps the known BlendCap BVH skeleton onto common MMD Tools
bone names (Japanese, English, and the usual side-suffix variants).
"""

import re
import unicodedata


ROOT_TARGETS = (
    "センター",
    "Center",
    "全ての親",
    "ParentNode",
    "グルーブ",
    "Groove",
    "腰",
    "Waist",
)

HIPS_ROT_TARGETS = (
    "腰",
    "Waist",
    "グルーブ",
    "Groove",
    "センター",
    "Center",
)

HIPS_VERTICAL_TARGETS = (
    "グルーブ",
    "Groove",
    "センター",
    "Center",
    "腰",
    "Waist",
    "全ての親",
    "ParentNode",
)


SPINE_TARGETS = (
    ("Spine", ("下半身", "LowerBody", "Spine")),
    ("Spine1", ("上半身", "UpperBody", "Spine1")),
    ("Spine2", ("上半身2", "UpperBody2", "Spine2")),
    ("Spine3", ("上半身3", "UpperBody3", "Spine3")),
)


CORE_LIMBS = (
    ("LeftShoulder", ("肩", "Shoulder", "Clavicle")),
    ("LeftArm", ("腕", "Arm", "UpperArm")),
    ("LeftForeArm", ("ひじ", "肘", "Elbow", "ForeArm", "Forearm", "LowerArm")),
    ("LeftHand", ("手首", "Wrist", "Hand")),
    ("LeftUpLeg", ("足", "Leg", "UpLeg", "Thigh")),
    ("LeftLeg", ("ひざ", "Knee")),
    ("LeftFoot", ("足首", "Ankle", "Foot")),
    ("LeftToe", ("つま先", "爪先", "Toe")),
)


FINGER_TARGETS = (
    ("Thumb1", ("親指０", "Thumb0", "親指１", "Thumb1")),
    ("Thumb2", ("親指１", "Thumb1", "親指２", "Thumb2")),
    ("Thumb3", ("親指２", "Thumb2", "親指３", "Thumb3")),
    ("Index1", ("人指１", "IndexFinger1", "人差指１", "Index1")),
    ("Index2", ("人指２", "IndexFinger2", "人差指２", "Index2")),
    ("Index3", ("人指３", "IndexFinger3", "人差指３", "Index3")),
    ("Middle1", ("中指１", "MiddleFinger1", "Middle1")),
    ("Middle2", ("中指２", "MiddleFinger2", "Middle2")),
    ("Middle3", ("中指３", "MiddleFinger3", "Middle3")),
    ("Ring1", ("薬指１", "RingFinger1", "Ring1")),
    ("Ring2", ("薬指２", "RingFinger2", "Ring2")),
    ("Ring3", ("薬指３", "RingFinger3", "Ring3")),
    ("Pinky1", ("小指１", "LittleFinger1", "Pinky1")),
    ("Pinky2", ("小指２", "LittleFinger2", "Pinky2")),
    ("Pinky3", ("小指３", "LittleFinger3", "Pinky3")),
)


FINGER_SOURCE = {
    "Thumb": "LeftHandThumb",
    "Index": "LeftHandIndex",
    "Middle": "LeftHandMiddle",
    "Ring": "LeftHandRing",
    "Pinky": "LeftHandPinky",
}

SOMA_REQUIRED = {
    "Hips", "Spine1", "Spine2", "Chest", "Neck1", "Neck2", "Head",
    "LeftArm", "LeftForeArm", "LeftHand", "RightArm", "RightForeArm", "RightHand",
    "LeftLeg", "LeftShin", "LeftFoot", "RightLeg", "RightShin", "RightFoot",
}

BLENDCAP_REQUIRED = (
    "Hips", "Spine", "Spine1", "Neck", "Head",
    "LeftArm", "LeftForeArm", "LeftHand", "RightArm", "RightForeArm", "RightHand",
    "LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot",
)


_TRAILING_INDEX_RE = re.compile(r"^(.*?)[._](\d{2,})$")


def _norm(name):
    return unicodedata.normalize("NFKC", name or "").strip().lower()


def _lookup_key(name):
    """Normalized name, with Blender's '.001' duplicate suffix removed."""
    n = _norm(name)
    match = _TRAILING_INDEX_RE.match(n)
    return match.group(1) if match else n


def _target_variants(stem, side):
    stem = _norm(stem)
    if not side:
        yield stem
        return
    side = _norm(side)
    for sep in (".", "_", "-", " "):
        yield f"{stem}{sep}{side}"
    yield f"{stem}{side}"
    prefix = "left" if side == "l" else "right"
    yield f"{prefix}{stem}"
    yield f"{prefix} {stem}"
    jp_prefix = "左" if side == "l" else "右"
    yield f"{jp_prefix}{stem}"


def _source_exists(expected, source_names):
    exp = _norm(expected)
    for name in source_names:
        key = _lookup_key(name)
        if key == exp:
            return True
        if len(key) > len(exp) and key.endswith(exp) and key[-len(exp) - 1] in ":._-":
            return True
    return False


def detect_source_profile(source_names):
    """Classify source semantics before mapping LeftLeg.

    SOMA and BlendCap BVH use the same label for different leg segments, so
    an unknown/partial profile must never be guessed.
    """
    names = set(source_names)
    if SOMA_REQUIRED.issubset(names) and "LeftShin" in names and "LeftUpLeg" not in names:
        return "SOMA_CANONICAL"
    if all(_source_exists(name, source_names) for name in BLENDCAP_REQUIRED):
        return "BLENDCAP_BVH"
    return "UNKNOWN"


def _find_target(stems, side, target_lookup):
    for stem in stems:
        for variant in _target_variants(stem, side):
            if variant in target_lookup:
                return target_lookup[variant]
    return None


def _is_descendant(name, ancestor, parents):
    cur = name
    seen = set()
    while cur is not None and cur not in seen:
        if cur == ancestor:
            return True
        seen.add(cur)
        cur = parents.get(cur)
    return False


def _depth(name, parents):
    depth = 0
    cur = parents.get(name)
    seen = set()
    while cur is not None and cur not in seen:
        depth += 1
        seen.add(cur)
        cur = parents.get(cur)
    return depth


def _resolve_hips_target(target_lookup, target_parents=None):
    """Pick the pelvis bone that can feed both legs and the spine via FK.

    MMD layouts vary: 腰 may sit above or below 下半身.  With parent
    information we choose the deepest named hip candidate that is still a
    common ancestor of the thigh targets and the first Spine target, so
    Hips rotation reaches the whole chain without inverting the hierarchy.
    """
    if not target_parents:
        return _find_target(HIPS_ROT_TARGETS, None, target_lookup)
    spine_target = _find_target(SPINE_TARGETS[0][1], None, target_lookup)
    left_leg = _find_target(("足", "Leg", "UpLeg", "Thigh"), "L", target_lookup)
    right_leg = _find_target(("足", "Leg", "UpLeg", "Thigh"), "R", target_lookup)

    candidates = []
    for stem in HIPS_ROT_TARGETS:
        target = _find_target((stem,), None, target_lookup)
        if target is not None and target not in candidates:
            candidates.append(target)

    def is_eligible(name):
        if left_leg and right_leg:
            if not (
                _is_descendant(left_leg, name, target_parents)
                and _is_descendant(right_leg, name, target_parents)
            ):
                return False
        if spine_target and not _is_descendant(spine_target, name, target_parents):
            return False
        return True

    eligible = [c for c in candidates if is_eligible(c)]
    if eligible:
        return max(eligible, key=lambda c: _depth(c, target_parents))

    leg_only = [
        c for c in candidates
        if left_leg and right_leg
        and _is_descendant(left_leg, c, target_parents)
        and _is_descendant(right_leg, c, target_parents)
    ]
    if leg_only:
        return max(leg_only, key=lambda c: _depth(c, target_parents))
    return _find_target(HIPS_ROT_TARGETS, None, target_lookup)


def detect_source_prefix(source_names, expected_names):
    """Return the separator-terminated prefix BlendCap BVH bones carry, or ''."""
    expected = [_norm(e) for e in expected_names if e]
    if not expected:
        return ""
    tally = {}
    for bone in source_names:
        key = _lookup_key(bone)
        for exp in expected:
            if len(key) > len(exp) and key.endswith(exp) and key[-len(exp) - 1] in ":._-":
                prefix = bone[: -len(exp)]
                tally[prefix] = tally.get(prefix, 0) + 1
                break
    if not tally:
        return ""
    return max(tally, key=lambda k: (tally[k], len(k)))


def build_mapping(source_bone_names, target_bone_names, target_parents=None, target_aliases=None):
    """Return (pairs, missing_labels) for the two armatures' bone names."""
    source_names = list(source_bone_names)
    target_lookup = {}
    for name in target_bone_names:
        target_lookup.setdefault(_lookup_key(name), name)
    for name, aliases in (target_aliases or {}).items():
        if name not in target_bone_names:
            continue
        for alias in aliases:
            key = _lookup_key(alias)
            if key:
                target_lookup.setdefault(key, name)

    pairs = []
    missing = []

    def add_pair(source, stems, side=None, channels="ROT", axes=None, label=None):
        if not _source_exists(source, source_names):
            return
        target = _find_target(stems, side, target_lookup)
        if target is None:
            missing.append(label or source)
            return
        pair = {
            "source": source,
            "target": target,
            "channels": channels,
            "influence": 1.0,
        }
        if axes:
            pair["axes"] = axes
        pairs.append(pair)

    def add_pair_target(source, target, channels="ROT", axes=None, label=None):
        if not _source_exists(source, source_names):
            return
        if target is None:
            missing.append(label or source)
            return
        pair = {
            "source": source,
            "target": target,
            "channels": channels,
            "influence": 1.0,
        }
        if axes:
            pair["axes"] = axes
        pairs.append(pair)

    # Head and neck.
    add_pair("Neck", ("首", "Neck"))
    add_pair("Head", ("頭", "Head"))

    # Spine chain (optional Spine3 for models with 上半身3).
    for source, stems in SPINE_TARGETS:
        add_pair(source, stems)

    # Hips rotation + vertical root offset.  With hierarchy info, pick the
    # pelvis root that is a common ancestor of the legs and the spine
    # target; this avoids the inverted 腰 <-> 下半身 layouts found in
    # some MMD models.  Without hierarchy info, keep the legacy naming
    # order exactly as before.
    if target_parents:
        hips_target = _resolve_hips_target(target_lookup, target_parents)
        if _source_exists("Hips", source_names):
            if hips_target is None:
                missing.append("Hips")
            else:
                add_pair_target("Hips", hips_target)
                add_pair_target("Hips", hips_target, channels="LOC", axes="Z")
    else:
        add_pair("Hips", HIPS_ROT_TARGETS)
        add_pair("Hips", HIPS_VERTICAL_TARGETS, channels="LOC", axes="Z")

    # Arms, hands, legs.
    for source, stems in CORE_LIMBS:
        rest = source[4:]  # "LeftShoulder" -> "Shoulder"
        for side in ("L", "R"):
            side_source = ("Right" if side == "R" else "Left") + rest
            label = f"{side_source} -> {stems[0]}.{side}"
            add_pair(side_source, stems, side=side, label=label)

    # Fingers: one pair per BlendCap finger bone on each side.  The source
    # bone name must follow the side, not stay on the LeftHand stem.
    finger_stems = dict(FINGER_TARGETS)
    for finger, left_stem in FINGER_SOURCE.items():
        for index in (1, 2, 3):
            stems = finger_stems[f"{finger}{index}"]
            for side in ("L", "R"):
                side_stem = ("Right" if side == "R" else "Left") + left_stem[4:]
                source = f"{side_stem}{index}"
                label = f"{source} -> {stems[0]}.{side}"
                add_pair(source, stems, side=side, label=label)

    # Root translation: XY lands on the MMD center, Z on the vertical root.
    add_pair("Root", ROOT_TARGETS, channels="LOC", axes="XY")

    return pairs, missing
