"""Pure-Python unit tests for ARKit -> MMD face mapping."""

import importlib.util
import os
import sys

import numpy as np


DEV = os.path.dirname(os.path.abspath(__file__))
module_path = os.path.join(DEV, "blendcap_motion_bridge", "face_mapper.py")
spec = importlib.util.spec_from_file_location("face_mapper", module_path)
face_mapper = importlib.util.module_from_spec(spec)
sys.modules["face_mapper"] = face_mapper
spec.loader.exec_module(face_mapper)


ARKIT_NAMES = [
    "BrowInnerUp", "BrowDownLeft", "BrowDownRight", "BrowOuterUpLeft",
    "BrowOuterUpRight", "eyeLookUpLeft", "eyeLookUpRight",
    "eyeLookDownLeft", "eyeLookDownRight", "eyeLookInLeft",
    "eyeLookInRight", "eyeLookOutLeft", "eyeLookOutRight",
    "eyeBlinkLeft", "eyeBlinkRight", "eyeSquintLeft", "eyeSquintRight",
    "eyeWideLeft", "eyeWideRight", "cheekPuff", "cheekSquintLeft",
    "cheekSquintRight", "noseSneerLeft", "noseSneerRight", "jawOpen",
    "jawForward", "jawLeft", "jawRight", "mouthFunnel", "mouthPucker",
    "mouthLeft", "mouthRight", "mouthRollUpper", "mouthRollLower",
    "mouthShrugUpper", "mouthShrugLower", "mouthClose", "mouthSmileLeft",
    "mouthSmileRight", "mouthFrownLeft", "mouthFrownRight",
    "mouthDimpleLeft", "mouthDimpleRight", "mouthUpperUpLeft",
    "mouthUpperUpRight", "mouthLowerDownLeft", "mouthLowerDownRight",
    "mouthPressLeft", "mouthPressRight", "mouthStretchLeft",
    "mouthStretchRight", "tongueOut",
]

MMD_KEYS = [
    "Basis", "う", "まばたき", "笑い", "笑い1", "ウィンク", "ウィンク右",
    "ウィンク２", "あ", "い", "E", "お",
]


def test_direct_arkit_mapping():
    channels = face_mapper.build_face_channels(ARKIT_NAMES, ARKIT_NAMES)
    assert len(channels) == len(ARKIT_NAMES)
    assert all(c.target == ARKIT_NAMES[i] for i, c in enumerate(channels))
    assert all(c.combine == "sum" for c in channels)


def test_mmd_fallback_mapping():
    channels = face_mapper.build_face_channels(ARKIT_NAMES, MMD_KEYS)
    by_target = {c.target: c for c in channels}
    blink = by_target["まばたき"]
    assert blink.combine == "max"
    blink_sources = {ARKIT_NAMES[i] for i, _w in blink.sources}
    assert blink_sources == {"eyeBlinkLeft", "eyeBlinkRight"}
    assert by_target["あ"].sources[0][0] == ARKIT_NAMES.index("jawOpen")
    assert "E" in by_target
    assert "ウィンク" in by_target
    assert "ウィンク右" in by_target


def test_mixed_model_avoids_duplicate_driving():
    channels = face_mapper.build_face_channels(ARKIT_NAMES, ARKIT_NAMES + MMD_KEYS)
    targets = [c.target for c in channels]
    assert len(targets) == len(set(targets))
    assert "eyeBlinkLeft" in targets
    assert "eyeBlinkRight" in targets
    # Fully covered fallbacks are skipped so the same expression is not
    # double-driven through an ARKit key and its Japanese duplicate.
    assert "まばたき" not in targets
    assert "あ" not in targets
    assert "E" not in targets

    # A fallback still runs when one of its ARKit sources is unavailable.
    missing = [name for name in ARKIT_NAMES if name != "mouthPucker"]
    channels = face_mapper.build_face_channels(missing, ARKIT_NAMES + MMD_KEYS)
    targets = [c.target for c in channels]
    assert len(targets) == len(set(targets))
    assert "う" in targets
    assert "お" in targets


def test_expanded_mmd_rule_coverage():
    white_like_keys = [
        "Basis", "まゆげ1", "まばたき", "笑い", "ウィンク", "ウィンク右",
        "ウィンク２", "ｳｨﾝｸ２右", "じと目", "びっくり", "困る", "上", "下",
        "瞳左", "瞳右", "あ", "い", "う", "え", "お", "口角上げ",
        "口角上げ1", "△",
    ]
    channels = face_mapper.build_face_channels(ARKIT_NAMES, white_like_keys)
    targets = [c.target for c in channels]
    assert len(targets) == len(set(targets))
    for expected in (
        "まゆげ1", "まばたき", "笑い", "ウィンク", "ウィンク右",
        "ウィンク２", "ｳｨﾝｸ２右", "じと目", "びっくり", "困る", "上",
        "下", "瞳左", "瞳右", "あ", "い", "う", "え", "お", "口角上げ",
        "口角上げ1", "△",
    ):
        assert expected in targets, expected


def test_compose_values():
    channels = face_mapper.build_face_channels(ARKIT_NAMES, MMD_KEYS)
    data = np.zeros((4, len(ARKIT_NAMES)), dtype=np.float32)
    data[0, ARKIT_NAMES.index("eyeBlinkLeft")] = 0.7
    data[0, ARKIT_NAMES.index("eyeBlinkRight")] = 0.3
    data[1, ARKIT_NAMES.index("eyeBlinkLeft")] = 0.2
    data[1, ARKIT_NAMES.index("eyeBlinkRight")] = 0.8
    data[2, ARKIT_NAMES.index("eyeBlinkLeft")] = 0.7
    data[2, ARKIT_NAMES.index("eyeBlinkRight")] = 0.65
    data[3, ARKIT_NAMES.index("jawOpen")] = 0.8
    vals = face_mapper.compose_values(data, channels)
    by_target = {c.target: i for i, c in enumerate(channels)}
    assert vals[0, by_target["まばたき"]] == 0.0
    assert vals[0, by_target["ウィンク"]] == 0.7
    assert vals[0, by_target["ウィンク右"]] == 0.0
    assert vals[1, by_target["まばたき"]] == 0.0
    assert vals[1, by_target["ウィンク"]] == 0.0
    assert vals[1, by_target["ウィンク右"]] == 0.8
    assert vals[2, by_target["まばたき"]] == 0.7
    assert vals[2, by_target["ウィンク"]] == 0.0
    assert vals[2, by_target["ウィンク右"]] == 0.0
    assert vals[3, by_target["あ"]] == 0.8
    assert vals.shape == (4, len(channels))


def test_direct_arkit_eyes_are_exclusive():
    channels = face_mapper.build_face_channels(ARKIT_NAMES, ARKIT_NAMES)
    data = np.zeros((2, len(ARKIT_NAMES)), dtype=np.float32)
    data[0, ARKIT_NAMES.index("eyeBlinkLeft")] = 0.8
    data[0, ARKIT_NAMES.index("eyeBlinkRight")] = 0.3
    data[1, ARKIT_NAMES.index("eyeBlinkLeft")] = 0.7
    data[1, ARKIT_NAMES.index("eyeBlinkRight")] = 0.65
    vals = face_mapper.compose_values(data, channels)
    by_target = {c.target: i for i, c in enumerate(channels)}
    assert vals[0, by_target["eyeBlinkLeft"]] == 0.8
    assert vals[0, by_target["eyeBlinkRight"]] == 0.0
    assert vals[1, by_target["eyeBlinkLeft"]] == 0.7
    assert vals[1, by_target["eyeBlinkRight"]] == 0.7


def main():
    test_direct_arkit_mapping()
    test_mmd_fallback_mapping()
    test_mixed_model_avoids_duplicate_driving()
    test_expanded_mmd_rule_coverage()
    test_compose_values()
    test_direct_arkit_eyes_are_exclusive()
    print("FACE_MAPPER_OK")


if __name__ == "__main__":
    main()
