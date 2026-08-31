"""Single, workflow-ordered panel for BlendCap Motion Bridge."""

import bpy


def _section(layout, title, icon):
    box = layout.box()
    box.label(text=title, icon=icon)
    return box


def _draw_mapping_result(layout, scene):
    status = layout.row()
    status.alert = scene.blendcap_motion_bridge_status_level == "ERROR"
    status.label(
        text=scene.blendcap_motion_bridge_status,
        icon=(
            "ERROR"
            if status.alert
            else ("CHECKMARK" if scene.blendcap_motion_bridge_status_level == "READY" else "INFO")
        ),
    )
    if not scene.blendcap_motion_bridge_total:
        return

    result = layout.column(align=True)
    result.label(text=f"映射 {scene.blendcap_motion_bridge_matched}/{scene.blendcap_motion_bridge_total}")
    if scene.blendcap_motion_bridge_critical_missing:
        result.label(text=f"关键缺失：{scene.blendcap_motion_bridge_critical_missing}", icon="ERROR")
    unmatched = [item for item in scene.blendcap_motion_bridge_unmatched.split(",") if item]
    if unmatched:
        result.label(text="可选未匹配：", icon="INFO")
        for item in unmatched[:6]:
            result.label(text=item)
        if len(unmatched) > 6:
            result.label(text=f"…另有 {len(unmatched) - 6} 项")


def _draw_face(layout, scene):
    face = _section(layout, "3 · MMD 表情", "SHAPEKEY_DATA")
    face.prop(scene, "blendcap_motion_bridge_face_npz", text="表情数据")
    face.prop_search(
        scene,
        "blendcap_motion_bridge_face_mesh",
        bpy.data,
        "objects",
        text="目标网格",
    )
    face.operator("blendcap_motion_bridge.apply_face", text="应用表情", icon="SHAPEKEY_DATA")
    if scene.blendcap_motion_bridge_face_total:
        face.label(text=f"匹配 {scene.blendcap_motion_bridge_face_matched}/{scene.blendcap_motion_bridge_face_total}")


def _draw_vmd_import(layout, scene):
    vmd = _section(layout, "4 · VMD 与烘焙后处理", "CONSTRAINT_BONE")
    vmd.prop_search(
        scene,
        "blendcap_motion_bridge_vmd_target",
        bpy.data,
        "objects",
        text="MMD 骨架",
    )
    vmd.label(text="导入 VMD 后", icon="IMPORT")
    row = vmd.row(align=True)
    row.operator("blendcap_motion_bridge.disable_leg_overrides", text="关闭腿部覆盖")
    row.operator("blendcap_motion_bridge.restore_leg_overrides", text="恢复腿 IK")
    vmd.separator()
    vmd.label(text="烘焙动作 / 姿态后", icon="RENDER_ANIMATION")
    vmd.operator("blendcap_motion_bridge.relink_leg_deform", text="重连腿部形变", icon="CONSTRAINT_BONE")
    if scene.blendcap_motion_bridge_vmd_ik_disabled:
        vmd.label(text=f"已关闭腿 IK：{scene.blendcap_motion_bridge_vmd_ik_disabled}", icon="INFO")
    if scene.blendcap_motion_bridge_vmd_cancel_disabled:
        vmd.label(text=f"已关闭腰取消：{scene.blendcap_motion_bridge_vmd_cancel_disabled}", icon="INFO")
    if scene.blendcap_motion_bridge_vmd_deform_relinked:
        vmd.label(text=f"已重连腿形变：{scene.blendcap_motion_bridge_vmd_deform_relinked}", icon="CHECKMARK")


class BCMB_PT_main(bpy.types.Panel):
    bl_label = "BlendCap Motion Bridge"
    bl_idname = "BCMB_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlendCap"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        scene = context.scene
        blendcap_ready = hasattr(bpy.types.Scene, "blendcap_retarget_source")

        source = _section(layout, "1 · 动作来源与角色", "ARMATURE_DATA")
        if blendcap_ready:
            source.prop(scene, "blendcap_retarget_source", text="BVH 来源")
            source.prop(scene, "blendcap_retarget_target", text="MMD 目标")
            source.operator("blendcap_motion_bridge.auto_select", text="自动识别来源与目标", icon="VIEWZOOM")
        else:
            warning = source.row()
            warning.alert = True
            warning.label(text="请先启用 BlendCap", icon="ERROR")
        source.label(text="传统 BlendCap BVH；SOMA 请使用 BA Motion Bridge", icon="INFO")

        retarget = _section(layout, "2 · 动作重定向", "ACTION")
        run = retarget.column()
        run.enabled = blendcap_ready
        run.scale_y = 1.4
        run.operator("blendcap_motion_bridge.quick_retarget", text="自动准备并安全重定向", icon="PLAY")
        retarget.label(text="内存映射 · 独立 Action · 不写 preset", icon="LOCKED")
        _draw_mapping_result(retarget, scene)

        retarget.separator()
        retarget.label(text="手动映射与 Preset（可选）", icon="PREFERENCES")
        manual = retarget.column()
        manual.enabled = blendcap_ready
        row = manual.row(align=True)
        row.operator("blendcap_motion_bridge.detect", text="只检查")
        row.operator("blendcap_motion_bridge.prepare_in_memory", text="载入内存表")
        manual.operator("blendcap_motion_bridge.write_preset", text="原子保存 Preset", icon="FILE_TICK")
        retarget.label(text="同名旧文件保留单份 .bak", icon="LOCKED")
        if scene.blendcap_motion_bridge_last_preset:
            retarget.label(text=f"Preset：{scene.blendcap_motion_bridge_last_preset}", icon="FILE")
        if scene.blendcap_motion_bridge_last_backup:
            retarget.label(text=f"备份：{scene.blendcap_motion_bridge_last_backup}", icon="RECOVER_LAST")

        if (
            scene.blendcap_motion_bridge_previous_state_available
            or scene.blendcap_motion_bridge_constraint_snapshot
            or scene.blendcap_motion_bridge_previous_table_json
        ):
            retarget.separator()
            retarget.operator("blendcap_motion_bridge.restore_previous_state", icon="LOOP_BACK")

        _draw_face(layout, scene)
        _draw_vmd_import(layout, scene)


CLASSES = (BCMB_PT_main,)
