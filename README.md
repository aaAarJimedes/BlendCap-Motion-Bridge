# BlendCap Motion Bridge

BlendCap Motion Bridge is a Blender extension that connects BlendCap motion
capture with MMD Tools characters. It provides deterministic BVH-to-MMD bone
mapping, safe retargeting, ARKit-to-MMD facial mapping, and post-bake leg-chain
repair in one clean, workflow-ordered sidebar panel.

## Highlights

- One panel, ordered from source selection to delivery cleanup
- Automatic BlendCap BVH to MMD bone mapping
- FK-safe retargeting that protects MMD leg motion from IK overrides
- ARKit facial capture mapping for direct and Japanese MMD morph names
- VMD import cleanup, leg IK restoration, and post-bake deform-chain relinking
- Full internal identity under \`blendcap_motion_bridge\`

## Requirements

- Blender 4.2 or newer (tested with Blender 5.1.2)
- [BlendCap](https://github.com/Arcomade/BlendCap)
- MMD Tools

## Install

Run the build script:

\`\`\`powershell
python .\build_zip.py
\`\`\`

Then install the generated \`blendcap_motion_bridge-<version>.zip\` from
Blender's **Edit > Preferences > Get Extensions > Install from Disk**.

The add-on appears in **3D Viewport > Sidebar > BlendCap** as a single
**BlendCap Motion Bridge** panel. Follow its numbered sections from top to
bottom:

1. Motion source and character
2. Motion retargeting
3. MMD facial animation
4. VMD and post-bake cleanup

## Development

Pure Python mapping checks:

\`\`\`powershell
python .\test_mapper.py
python .\test_face_mapper.py
python .\test_safety_profiles.py
\`\`\`

Factory-startup registration check:

\`\`\`powershell
blender --background --factory-startup --python-exit-code 1 --python .\test_registration_040.py
\`\`\`

Isolated Blender integration regression:

\`\`\`powershell
powershell -ExecutionPolicy Bypass -File .\tests\run_integration_040.ps1 -BlenderPath "C:\path\to\blender.exe"
\`\`\`

## Identity migration

Version 0.3.0 is a breaking identity migration from the former MMD2BlendCap
development name. The manifest ID, Python package, operator namespace, Scene
RNA properties, panel classes, action ownership tags, and preset prefix now
use \`blendcap_motion_bridge\`, \`BCMB_*\`, or \`blendcap_motion_bridge_*\` as
appropriate. Legacy IDs are not registered.

## Negative-frame pre-roll

Version 0.4.0 can create a recorded pre-roll range before the first real
retargeted frame without shifting the motion itself. Choose the initial pose
from the target's current pose, its Rest Pose, or a selected Action frame, then
set independent hold and transition durations. For example, a 30-frame buffer
in front of real frame 1 occupies frames -29 through 0, while frame 1 and every
later motion, face, camera, and audio timecode remain unchanged.

The retarget operation writes and evaluates the negative-frame transition and
moves the rigid-body point-cache start to the pre-roll start when an MMD rigid
body world is present. Bake skirt and hair physics with that range included.
After the physics result has been baked to animation keys, confirm the bake in
the panel and run **Finish and Clean Pre-roll**. Cleanup deletes only keys
before the recorded real motion start; it never shifts production keys.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
