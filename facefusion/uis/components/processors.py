from typing import List, Optional, Tuple
import gradio  # 保持你项目原本的用法

from facefusion import state_manager, wording
from facefusion.filesystem import get_file_name, resolve_file_paths
from facefusion.processors.core import get_processors_modules
from facefusion.uis.core import register_ui_component

# ====== 内部ID -> 中文标签（没写的就用原ID显示） ======
PROCESSOR_LABELS = {
    "face_swapper": "人脸替换",
    "age_modifier": "年龄调整",
    "deep_swapper": "深度替换",
    "expression_restorer": "表情恢复",
    "face_debugger": "人脸调试",
    "face_editor": "人脸编辑",
    "face_enhancer": "人脸增强",
    "frame_colorizer": "画面上色",
    "frame_enhancer": "画面增强",
    "lip_syncer": "唇形同步",
}

PROCESSORS_CHECKBOX_GROUP: Optional[gradio.CheckboxGroup] = None


def _available_ids() -> List[str]:
    # 按磁盘扫描顺序，保持原项目行为
    return [get_file_name(p) for p in resolve_file_paths('facefusion/processors/modules')]


def _current_ids() -> List[str]:
    cur = state_manager.get_item('processors')
    return cur if isinstance(cur, list) else []


def _ordered_ids(selected_ids: List[str], available_ids: List[str]) -> List[str]:
    """
    原版顺序策略：
    1) 已选项保持当前顺序置前
    2) 其余按扫描顺序补齐
    """
    seen = set()
    out: List[str] = []
    for pid in (selected_ids or []):
        if pid in available_ids and pid not in seen:
            out.append(pid); seen.add(pid)
    for pid in available_ids:
        if pid not in seen:
            out.append(pid)
    return out


def _make_choices(selected_ids: List[str], available_ids: List[str]) -> List[Tuple[str, str]]:
    """
    返回 (label, value)：
    - label 显示中文
    - value 永远是内部ID（避免“值不在 choices 里”的问题）
    """
    ordered = _ordered_ids(selected_ids, available_ids)
    return [(PROCESSOR_LABELS.get(pid, pid), pid) for pid in ordered]


def render() -> None:
    global PROCESSORS_CHECKBOX_GROUP
    all_ids = _available_ids()
    selected_ids = [x for x in _current_ids() if x in all_ids]

    PROCESSORS_CHECKBOX_GROUP = gradio.CheckboxGroup(
        label=wording.get('uis.processors_checkbox_group'),
        choices=_make_choices(selected_ids, all_ids),  # (中文, 内部ID)
        value=selected_ids                              # 内部ID
    )
    register_ui_component('processors_checkbox_group', PROCESSORS_CHECKBOX_GROUP)


def listen() -> None:
    if PROCESSORS_CHECKBOX_GROUP is None:
        return
    PROCESSORS_CHECKBOX_GROUP.change(
        update_processors,
        inputs=PROCESSORS_CHECKBOX_GROUP,
        outputs=PROCESSORS_CHECKBOX_GROUP
    )


def update_processors(new_selected_ids: List[str]):
    """
    Gradio 传入的是内部ID列表（因为 choices 用的是 (label, value)）。
    仅对“新增”的做 pre_check，失败只回滚那几个；不新建组件，返回 gr.update。
    """
    all_ids_list = _available_ids()
    all_ids = set(all_ids_list)

    # 过滤无效ID
    new_selected_ids = [x for x in (new_selected_ids or []) if x in all_ids]
    old_ids = _current_ids()

    # 只对新增做预检
    added = [x for x in new_selected_ids if x not in old_ids]
    failed: List[str] = []
    for pid in added:
        ok = True
        for m in get_processors_modules([pid]):
            try:
                if hasattr(m, 'pre_check') and not m.pre_check():
                    ok = False
                    break
            except Exception:
                ok = False
                break
        if not ok:
            failed.append(pid)

    # 去掉预检失败的新增项
    final_ids = [x for x in new_selected_ids if x not in failed]

    # 清理被移除的
    removed = [x for x in old_ids if x not in final_ids]
    for m in get_processors_modules(removed):
        if hasattr(m, 'clear_inference_pool'):
            try:
                m.clear_inference_pool()
            except Exception:
                pass

    # 写状态（只存内部ID）
    state_manager.set_item('processors', final_ids)

    # 更新UI：顺序=已选置前（保持原顺序）+ 扫描顺序补齐
    return gradio.update(
        choices=_make_choices(final_ids, all_ids_list),
        value=final_ids
    )
