"""Pure-Python unit test for the deterministic MMD mapping logic."""

import importlib.util
import os
import sys


DEV = os.path.dirname(os.path.abspath(__file__))
mapper_path = os.path.join(DEV, "blendcap_motion_bridge", "mmd_mapper.py")
spec = importlib.util.spec_from_file_location("mmd_mapper", mapper_path)
mapper = importlib.util.module_from_spec(spec)
sys.modules["mmd_mapper"] = mapper
spec.loader.exec_module(mapper)


SOURCE = [
    "LeftHandThumb1",
    "LeftHandThumb2",
    "LeftHandThumb3",
    "RightHandThumb1",
    "RightHandThumb2",
    "RightHandThumb3",
    "LeftHandRing1",
    "LeftHandRing2",
    "LeftHandRing3",
    "RightHandRing1",
    "RightHandRing2",
    "RightHandRing3",
    "LeftToe",
    "RightToe",
]

TARGET = [
    "親指０.L",
    "親指０.R",
    "親指１.L",
    "親指１.R",
    "親指２.L",
    "親指２.R",
    "薬指１.L",
    "薬指１.R",
    "薬指２.L",
    "薬指２.R",
    "薬指３.L",
    "薬指３.R",
    "つま先.L",
    "つま先.R",
]


def _rotation_hips(pairs):
    return [
        p for p in pairs
        if p["source"] == "Hips" and p["channels"] == "ROT"
    ]


def test_hierarchy_hips_inverted_mmd_layout():
    source = ["Hips", "Spine"]
    target = ["グルーブ", "下半身", "腰", "足.L", "足.R"]
    parents = {
        "足.L": "腰",
        "足.R": "腰",
        "腰": "下半身",
        "下半身": "グルーブ",
        "グルーブ": None,
    }
    pairs, missing = mapper.build_mapping(source, target, parents)
    assert missing == [], missing
    hips = _rotation_hips(pairs)
    spine = [p for p in pairs if p["source"] == "Spine"]
    assert len(hips) == 1, hips
    assert hips[0]["target"] == "グルーブ", hips
    assert len(spine) == 1, spine
    assert spine[0]["target"] == "下半身", spine


def test_hierarchy_hips_standard_mmd_layout():
    source = ["Hips", "Spine"]
    target = [
        "グルーブ",
        "腰",
        "下半身",
        "腰キャンセル.L",
        "腰キャンセル.R",
        "足.L",
        "足.R",
    ]
    parents = {
        "足.L": "腰キャンセル.L",
        "足.R": "腰キャンセル.R",
        "腰キャンセル.L": "下半身",
        "腰キャンセル.R": "下半身",
        "下半身": "腰",
        "腰": "グルーブ",
        "グルーブ": None,
    }
    pairs, missing = mapper.build_mapping(source, target, parents)
    assert missing == [], missing
    hips = _rotation_hips(pairs)
    assert len(hips) == 1, hips
    assert hips[0]["target"] == "腰", hips


def test_legacy_hips_fallback_without_parents():
    pairs = mapper.build_mapping(
        ["Hips"],
        ["グルーブ", "下半身", "腰"],
    )[0]
    hips = _rotation_hips(pairs)
    assert len(hips) == 1, hips
    assert hips[0]["target"] == "腰", hips


def test_japanese_side_prefix_legs():
    pairs, missing = mapper.build_mapping(
        ["Hips", "LeftUpLeg", "RightUpLeg"],
        ["腰", "左足", "右足"],
    )
    assert missing == [], missing
    thighs = {
        p["target"]
        for p in pairs
        if p["source"] in ("LeftUpLeg", "RightUpLeg")
        and p["channels"] == "ROT"
    }
    assert thighs == {"左足", "右足"}, thighs


def main():
    pairs, missing = mapper.build_mapping(SOURCE, TARGET)
    got = {(p["source"], p["target"]) for p in pairs}

    expected = {
        ("LeftHandThumb1", "親指０.L"),
        ("RightHandThumb1", "親指０.R"),
        ("LeftHandThumb3", "親指２.L"),
        ("RightHandThumb3", "親指２.R"),
        ("LeftHandRing3", "薬指３.L"),
        ("RightHandRing3", "薬指３.R"),
        ("LeftToe", "つま先.L"),
        ("RightToe", "つま先.R"),
    }
    assert missing == [], missing
    assert expected <= got, expected - got
    assert len(got) == len(pairs), "duplicate pairs"
    test_hierarchy_hips_inverted_mmd_layout()
    test_hierarchy_hips_standard_mmd_layout()
    test_legacy_hips_fallback_without_parents()
    test_japanese_side_prefix_legs()
    print("TEST_OK", len(pairs), "pairs")


if __name__ == "__main__":
    main()
