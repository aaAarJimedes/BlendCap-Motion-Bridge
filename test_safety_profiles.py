"""Pure-Python safety gates for source semantics and MMD aliases."""

import importlib.util
from pathlib import Path


MODULE = Path(__file__).parent / "blendcap_motion_bridge" / "mmd_mapper.py"
spec = importlib.util.spec_from_file_location("mmd_mapper_safety", MODULE)
mapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mapper)


soma = set(mapper.SOMA_REQUIRED)
assert mapper.detect_source_profile(soma) == "SOMA_CANONICAL"

bvh = set(mapper.BLENDCAP_REQUIRED) | {"Root", "Spine2"}
assert mapper.detect_source_profile(bvh) == "BLENDCAP_BVH"
assert mapper.detect_source_profile(bvh - {"RightUpLeg"}) == "UNKNOWN"

target_names = [
    "root_ctrl", "hips_ctrl", "lower", "upper", "neck_ctrl", "head_ctrl",
    "arm_l", "elbow_l", "hand_l", "thigh_l", "knee_l", "ankle_l",
    "arm_r", "elbow_r", "hand_r", "thigh_r", "knee_r", "ankle_r",
]
aliases = {
    "root_ctrl": ("センター",),
    "hips_ctrl": ("腰",),
    "lower": ("下半身",),
    "upper": ("上半身",),
    "neck_ctrl": ("首",),
    "head_ctrl": ("頭",),
    "arm_l": ("腕.L",), "elbow_l": ("ひじ.L",), "hand_l": ("手首.L",),
    "thigh_l": ("足.L",), "knee_l": ("ひざ.L",), "ankle_l": ("足首.L",),
    "arm_r": ("腕.R",), "elbow_r": ("ひじ.R",), "hand_r": ("手首.R",),
    "thigh_r": ("足.R",), "knee_r": ("ひざ.R",), "ankle_r": ("足首.R",),
}
parents = {name: None for name in target_names}
pairs, missing = mapper.build_mapping(bvh, target_names, parents, aliases)
assert any(pair["source"] == "Neck" and pair["target"] == "neck_ctrl" for pair in pairs)
assert any(pair["source"] == "LeftUpLeg" and pair["target"] == "thigh_l" for pair in pairs)
assert not any(pair["source"] == "LeftLeg" and pair["target"] == "thigh_l" for pair in pairs)

print("BLENDCAP_MOTION_BRIDGE_SAFETY_PROFILES_OK", len(pairs), len(missing))
