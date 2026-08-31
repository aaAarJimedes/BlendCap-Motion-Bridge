"""Map BlendCap's ARKit face weights onto MMD Tools shape keys.

BlendCap's own ARKit apply expects the mesh to already carry ARKit-named
shape keys.  MMD models often only carry Japanese keys (まばたき, あ, ...),
so this module first matches ARKit names directly, then falls back to
deterministic compositions for the common MMD expressions.  Direct and
fallback channels are independent: a model with a few ARKit keys can still
use its Japanese morphs for every other expression.
"""

import dataclasses
import unicodedata

import numpy as np


@dataclasses.dataclass(frozen=True)
class FaceChannel:
    target: str
    sources: tuple
    combine: str = "sum"


# Each rule maps one or more MMD shape-key names to a weighted ARKit
# composition.  "max" picks the strongest source; "sum" adds weighted
# sources and clips the final value to [0, 1].
MMD_FALLBACK_RULES = (
    # Eyes: two-eye and one-eye blinks.
    (("まばたき", "blink", "まばた"), "max",
     (("eyeBlinkLeft", 1.0), ("eyeBlinkRight", 1.0))),
    (("ウィンク", "wink", "wink left", "winkL"), "max",
     (("eyeBlinkLeft", 1.0),)),
    (("ウィンク右", "wink right", "winkR"), "max",
     (("eyeBlinkRight", 1.0),)),
    (("ウィンク２", "ウィンク2", "wink2", "wink left2", "winkL2"), "max",
     (("eyeBlinkLeft", 1.0),)),
    (("ｳｨﾝｸ２右", "ウィンク2右", "wink right2", "winkR2"), "max",
     (("eyeBlinkRight", 1.0),)),

    # Other eye expressions and gaze.
    (("じと目", "deadpan"), "max",
     (("eyeSquintLeft", 1.0), ("eyeSquintRight", 1.0))),
    (("びっくり", "surprised"), "max",
     (("eyeWideLeft", 1.0), ("eyeWideRight", 1.0))),
    (("上", "look up", "lookup"), "max",
     (("eyeLookUpLeft", 1.0), ("eyeLookUpRight", 1.0))),
    (("下", "look down", "lookdown"), "max",
     (("eyeLookDownLeft", 1.0), ("eyeLookDownRight", 1.0))),
    (("左", "look left", "lookleft"), "max",
     (("eyeLookOutLeft", 1.0), ("eyeLookInRight", 1.0))),
    (("右", "look right", "lookright"), "max",
     (("eyeLookInLeft", 1.0), ("eyeLookOutRight", 1.0))),
    (("瞳左", "pupil left"), "max",
     (("eyeLookOutLeft", 1.0), ("eyeLookInRight", 1.0))),
    (("瞳右", "pupil right"), "max",
     (("eyeLookInLeft", 1.0), ("eyeLookOutRight", 1.0))),

    # Brows and mood expressions that mainly move the brows.
    (("まゆげ1", "眉上げ", "まゆ上げ", "brow up"), "max",
     (("BrowInnerUp", 1.0), ("BrowOuterUpLeft", 1.0),
      ("BrowOuterUpRight", 1.0))),
    (("眉下げ", "まゆ下げ", "brow down"), "max",
     (("BrowDownLeft", 1.0), ("BrowDownRight", 1.0))),
    (("困る", "troubled"), "max",
     (("BrowDownLeft", 1.0), ("BrowDownRight", 1.0))),
    (("怒り", "angry"), "max",
     (("BrowDownLeft", 1.0), ("BrowDownRight", 1.0),
      ("mouthFrownLeft", 0.5), ("mouthFrownRight", 0.5))),

    # Vowel morphs.
    (("あ", "a", "A"), "sum", (("jawOpen", 1.0),)),
    (("い", "i", "I"), "sum",
     (("mouthStretchLeft", 0.5), ("mouthStretchRight", 0.5))),
    (("う", "u", "U"), "sum",
     (("mouthFunnel", 0.8), ("mouthPucker", 0.2))),
    (("え", "e", "E"), "sum",
     (("mouthSmileLeft", 0.5), ("mouthSmileRight", 0.5))),
    (("お", "o", "O"), "sum",
     (("mouthPucker", 0.7), ("jawOpen", 0.3))),

    # Mouth expressions.
    (("笑い", "笑い1", "にこり", "にやり", "smile", "ha"), "max",
     (("mouthSmileLeft", 1.0), ("mouthSmileRight", 1.0),
      ("cheekSquintLeft", 1.0), ("cheekSquintRight", 1.0))),
    (("口角上げ", "mouth corner up"), "sum",
     (("mouthSmileLeft", 0.5), ("mouthSmileRight", 0.5))),
    (("口角上げ1",), "sum",
     (("mouthSmileLeft", 0.5), ("mouthSmileRight", 0.5))),
    (("口角下げ", "mouth corner down"), "sum",
     (("mouthFrownLeft", 0.5), ("mouthFrownRight", 0.5))),
    (("口真一文字", "mouth straight"), "max",
     (("mouthPressLeft", 1.0), ("mouthPressRight", 1.0))),
    (("頬", "cheek"), "sum", (("cheekPuff", 1.0),)),
    (("ぺろっ", "tongue"), "sum", (("tongueOut", 1.0),)),
    (("△", "triangle"), "sum",
     (("mouthFunnel", 0.5), ("jawOpen", 0.5))),
)


BLINK_LEFT_KEYS = (
    "eyeBlinkLeft",
    "ウィンク",
    "ウィンク２",
    "ウィンク2",
    "wink",
    "wink left",
    "winkL",
    "wink2",
    "winkL2",
)

BLINK_RIGHT_KEYS = (
    "eyeBlinkRight",
    "ウィンク右",
    "ｳｨﾝｸ２右",
    "ウィンク2右",
    "wink right",
    "winkR",
    "wink right2",
    "winkR2",
)

BLINK_BOTH_KEYS = (
    "まばたき",
    "blink",
    "まばた",
)


def _norm(name):
    return unicodedata.normalize("NFKC", name or "").strip().lower()


def build_face_channels(bs_names, shape_key_names):
    """Return FaceChannel list for the mesh's shape keys."""
    source_index = {}
    for i, name in enumerate(bs_names):
        source_index.setdefault(_norm(name), i)

    target_lookup = {}
    for name in shape_key_names:
        target_lookup.setdefault(_norm(name), name)

    channels = []
    seen_targets = set()
    direct_source_names = set()

    # ARKit-named shape keys are always driven directly with their source
    # value.  MMD Tools sometimes prefixes imported ARKit keys with "_".
    for i, bs_name in enumerate(bs_names):
        key = _norm(bs_name)
        target = target_lookup.get(key) or target_lookup.get(f"_{key}")
        if target is None:
            continue
        channels.append(FaceChannel(target, ((i, 1.0),), "sum"))
        seen_targets.add(_norm(target))
        direct_source_names.add(key)

    # Japanese/English MMD morphs are filled in as separate channels.  A rule
    # only runs when its morph exists on the mesh, has not already been driven,
    # and at least one ARKit source is missing from the direct set.  The last
    # condition prevents a mixed model from double-driving the same expression
    # through an ARKit key and its Japanese duplicate.
    for sk_names, combine, sources in MMD_FALLBACK_RULES:
        target = None
        for name in sk_names:
            key = _norm(name)
            if key in target_lookup:
                target = target_lookup[key]
                break
        if target is None or _norm(target) in seen_targets:
            continue
        if all(_norm(arkit) in direct_source_names for arkit, _weight in sources):
            continue
        resolved = tuple(
            (source_index[_norm(arkit)], weight)
            for arkit, weight in sources
            if _norm(arkit) in source_index
        )
        if not resolved:
            continue
        channels.append(FaceChannel(target, resolved, combine))
        seen_targets.add(_norm(target))

    return channels


def compose_values(blendshapes, channels):
    """Return (N, len(channels)) float32 weights clipped to [0, 1]."""
    vals = np.zeros((len(blendshapes), len(channels)), dtype=np.float32)
    for col, channel in enumerate(channels):
        if channel.combine == "max":
            for bs_idx, weight in channel.sources:
                np.maximum(
                    vals[:, col],
                    blendshapes[:, bs_idx] * weight,
                    out=vals[:, col],
                )
        else:
            for bs_idx, weight in channel.sources:
                vals[:, col] += blendshapes[:, bs_idx] * weight
    np.clip(vals, 0.0, 1.0, out=vals)
    _resolve_eye_conflicts(vals, channels)
    return vals


def _resolve_eye_conflicts(vals, channels):
    """Keep blink/wink channels exclusive so one-eye and two-eye closures
    do not stack on the same eye geometry."""
    left_cols = [
        i for i, channel in enumerate(channels)
        if _norm(channel.target) in {_norm(n) for n in BLINK_LEFT_KEYS}
    ]
    right_cols = [
        i for i, channel in enumerate(channels)
        if _norm(channel.target) in {_norm(n) for n in BLINK_RIGHT_KEYS}
    ]
    both_cols = [
        i for i, channel in enumerate(channels)
        if _norm(channel.target) in {_norm(n) for n in BLINK_BOTH_KEYS}
    ]

    if not left_cols or not right_cols:
        return

    left = np.maximum.reduce([vals[:, i] for i in left_cols])
    right = np.maximum.reduce([vals[:, i] for i in right_cols])

    for frame in range(len(vals)):
        l = float(left[frame])
        r = float(right[frame])
        peak = max(l, r)
        if peak <= 0.05:
            for i in left_cols + right_cols + both_cols:
                vals[frame, i] = 0.0
            continue
        if min(l, r) >= peak * 0.7:
            if both_cols:
                for i in both_cols:
                    vals[frame, i] = peak
                for i in left_cols + right_cols:
                    vals[frame, i] = 0.0
            else:
                for i in left_cols + right_cols:
                    vals[frame, i] = peak
            continue
        if both_cols:
            for i in both_cols:
                vals[frame, i] = 0.0
        if l >= r:
            for i in left_cols:
                vals[frame, i] = l
            for i in right_cols:
                vals[frame, i] = 0.0
        else:
            for i in right_cols:
                vals[frame, i] = r
            for i in left_cols:
                vals[frame, i] = 0.0
