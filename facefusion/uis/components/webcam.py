from typing import Generator, List, Optional, Tuple, Union
import os
from pathlib import Path
from typing import Any
import json
import zipfile
from uuid import uuid4
import json

import cv2
import gradio

from facefusion import state_manager, wording
from facefusion.camera_manager import clear_camera_pool, get_local_camera_capture
from facefusion.filesystem import has_image
from facefusion.streamer import multi_process_capture, open_stream
from facefusion.types import Fps, VisionFrame, WebcamMode
from facefusion.uis.core import get_ui_component
from facefusion.uis.types import File
from facefusion.vision import unpack_resolution
from facefusion.uis.monitor_integration import save_latest_frame

SOURCE_FILE: Optional[gradio.File] = None
SOURCE_DIR_UPLOAD: Optional[gradio.File] = None
SOURCE_FILES_UPLOAD: Optional[gradio.File] = None
SOURCE_GALLERY: Optional[gradio.Gallery] = None
WEBCAM_IMAGE: Optional[gradio.Image] = None
WEBCAM_START_BUTTON: Optional[gradio.Button] = None
WEBCAM_STOP_BUTTON: Optional[gradio.Button] = None
SOURCE_PATH_DISPLAY: Optional[gradio.Textbox] = None
GALLERY_EVT_DEBUG: Optional[gradio.Textbox] = None
DIR_UPLOAD_DEBUG: Optional[gradio.Textbox] = None
DEBUG_TOGGLE: Optional[gradio.Checkbox] = None


def render() -> None:
    global SOURCE_FILE
    global SOURCE_DIR_UPLOAD
    global SOURCE_FILES_UPLOAD
    global SOURCE_GALLERY
    global WEBCAM_IMAGE
    global WEBCAM_START_BUTTON
    global WEBCAM_STOP_BUTTON
    global SOURCE_PATH_DISPLAY
    global GALLERY_EVT_DEBUG
    global DIR_UPLOAD_DEBUG
    global DEBUG_TOGGLE

    has_source_image = has_image(state_manager.get_item("source_paths"))
    SOURCE_FILE = gradio.File(
        label=wording.get("uis.source_file"),
        file_count="multiple",
        value=state_manager.get_item("source_paths") if has_source_image else None,
        visible=False,
    )

    # 选择文件夹（使用 File 组件的 directory 模式）
    SOURCE_DIR_UPLOAD = gradio.File(
        label="选择文件夹",
        file_count="directory",
        type="filepath",
    )
    SOURCE_FILES_UPLOAD = gradio.File(
        label="选择图片文件",
        file_count="multiple",
        type="filepath",
        file_types=["image"],
        visible=False,
    )
    # —— 调试面板开关（系统设置） ——
    debug_enabled_default = bool(state_manager.get_item("debug_enabled") or False)
    with gradio.Accordion("系统设置", open=False):
        DEBUG_TOGGLE = gradio.Checkbox(
            label="显示调试面板",
            value=debug_enabled_default,
        )
    # Gallery 展示文件夹内的所有图片文件；始终可见
    SOURCE_GALLERY = gradio.Gallery(
        label="源图片库",
        object_fit="cover",
        allow_preview=True,
        columns=7,
        visible=True,
    )
    initial_paths = state_manager.get_item("source_paths") if has_source_image else None
    initial_display = initial_paths[0] if initial_paths else ""
    SOURCE_PATH_DISPLAY = gradio.Textbox(
        label="源文件路径",
        value=initial_display,
        interactive=False,
        lines=1,
        visible=debug_enabled_default,
    )
    GALLERY_EVT_DEBUG = gradio.Textbox(
        label="Gallery 事件调试",
        value="",
        interactive=False,
        lines=2,
        visible=debug_enabled_default,
    )
    DIR_UPLOAD_DEBUG = gradio.Textbox(
        label="目录上传调试",
        value="",
        interactive=False,
        lines=2,
        visible=debug_enabled_default,
    )
    WEBCAM_IMAGE = gradio.Image(
        label=wording.get("uis.webcam_image"), format="jpeg", visible=False
    )
    WEBCAM_START_BUTTON = gradio.Button(
        value=wording.get("uis.start_button"), variant="primary", size="sm"
    )
    WEBCAM_STOP_BUTTON = gradio.Button(
        value=wording.get("uis.stop_button"), size="sm", visible=False
    )


def listen() -> None:
    SOURCE_FILE.change(
        update_source, inputs=SOURCE_FILE, outputs=[SOURCE_FILE, SOURCE_PATH_DISPLAY]
    )

    # 解析上传的目录或多文件，填充 Gallery
    if SOURCE_DIR_UPLOAD and SOURCE_GALLERY:
        SOURCE_DIR_UPLOAD.change(
            update_gallery_from_dir_upload,
            inputs=SOURCE_DIR_UPLOAD,
            outputs=[SOURCE_GALLERY, DIR_UPLOAD_DEBUG],
        )
    if SOURCE_FILES_UPLOAD and SOURCE_GALLERY:
        SOURCE_FILES_UPLOAD.change(
            update_gallery_from_files_upload,
            inputs=SOURCE_FILES_UPLOAD,
            outputs=[SOURCE_GALLERY, DIR_UPLOAD_DEBUG],
        )
    # 调试开关事件：切换调试组件可见性并持久化
    if DEBUG_TOGGLE:
        DEBUG_TOGGLE.change(
            on_debug_toggle,
            inputs=DEBUG_TOGGLE,
            outputs=[SOURCE_PATH_DISPLAY, GALLERY_EVT_DEBUG, DIR_UPLOAD_DEBUG],
        )

    # Gallery 选择驱动 Source_file（保持不可见）及全局 source_paths
    if SOURCE_GALLERY:
        SOURCE_GALLERY.select(
            on_gallery_select,
            outputs=[SOURCE_FILE, SOURCE_PATH_DISPLAY, GALLERY_EVT_DEBUG],
        )
    webcam_device_id_dropdown = get_ui_component("webcam_device_id_dropdown")
    webcam_mode_radio = get_ui_component("webcam_mode_radio")
    webcam_resolution_dropdown = get_ui_component("webcam_resolution_dropdown")
    webcam_fps_slider = get_ui_component("webcam_fps_slider")

    if (
        webcam_device_id_dropdown
        and webcam_mode_radio
        and webcam_resolution_dropdown
        and webcam_fps_slider
    ):
        WEBCAM_START_BUTTON.click(
            pre_start,
            outputs=[
                SOURCE_FILE,
                WEBCAM_IMAGE,
                WEBCAM_START_BUTTON,
                WEBCAM_STOP_BUTTON,
            ],
        )
        start_event = WEBCAM_START_BUTTON.click(
            start,
            inputs=[
                webcam_device_id_dropdown,
                webcam_mode_radio,
                webcam_resolution_dropdown,
                webcam_fps_slider,
            ],
            outputs=WEBCAM_IMAGE,
        )
        start_event.then(pre_stop)
        WEBCAM_STOP_BUTTON.click(stop, cancels=start_event, outputs=WEBCAM_IMAGE)
        WEBCAM_STOP_BUTTON.click(
            pre_stop,
            outputs=[
                SOURCE_FILE,
                WEBCAM_IMAGE,
                WEBCAM_START_BUTTON,
                WEBCAM_STOP_BUTTON,
            ],
        )


def update_source(files: List[File]) -> Tuple[gradio.File, gradio.Textbox]:
    file_names = [file.name for file in files] if files else None
    has_source_image = has_image(file_names)

    if has_source_image:
        state_manager.set_item("source_paths", file_names)
        display_value = file_names[0] if file_names else ""
        return gradio.update(value=file_names), gradio.update(value=display_value)

    state_manager.clear_item("source_paths")
    return gradio.update(value=None), gradio.update(value="")


def _list_images_in_dir(dir_path: str) -> List[str]:
    if not dir_path:
        return []
    p = Path(dir_path)
    if not p.exists() or not p.is_dir():
        return []
    exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
    files: List[str] = []
    try:
        for item in p.iterdir():
            if item.is_file() and item.suffix.lower() in exts:
                files.append(str(item))
    except Exception:
        return []
    return sorted(files)


def _list_images_recursive(dir_path: str) -> List[str]:
    exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
    files: List[str] = []
    p = Path(dir_path)
    if not p.exists() or not p.is_dir():
        return []
    for root, _, filenames in os.walk(p):
        for name in filenames:
            if Path(name).suffix.lower() in exts:
                files.append(str(Path(root) / name))
    return sorted(files)


def update_gallery_from_dir_upload(dir_value: Any):
    dir_path: Optional[str] = None
    raw = None
    if isinstance(dir_value, list):
        raw = dir_value
        image_paths: List[str] = []
        for item in dir_value:
            if isinstance(item, str):
                image_paths.append(item)
            elif isinstance(item, dict):
                candidate = (
                    item.get("path") or item.get("file_path") or item.get("name")
                )
                if isinstance(candidate, str):
                    image_paths.append(candidate)
        image_paths = [p for p in image_paths if _is_image_path(p)]
        debug_payload = {
            "raw_type": "list",
            "raw_count": len(raw),
            "resolved_dir_path": None,
            "image_count": len(image_paths),
        }
        return (
            gradio.update(value=image_paths, visible=True),
            gradio.update(
                value=json.dumps(debug_payload, ensure_ascii=False, indent=2)
            ),
        )
    if isinstance(dir_value, Path):
        raw = str(dir_value)
        dir_value = raw
    elif isinstance(dir_value, dict):
        raw = dir_value
        candidate = (
            dir_value.get("path") or dir_value.get("file_path") or dir_value.get("name")
        )
        if isinstance(candidate, str):
            dir_value = candidate
    elif isinstance(dir_value, str):
        raw = dir_value

    if isinstance(dir_value, str):
        if os.path.isdir(dir_value):
            dir_path = dir_value
        elif dir_value.lower().endswith(".zip"):
            dir_path = _extract_zip_to_temp(dir_value)

    image_paths: List[str] = _list_images_recursive(dir_path) if dir_path else []
    debug_payload = {
        "raw": raw,
        "resolved_dir_path": dir_path,
        "image_count": len(image_paths),
    }
    return (
        gradio.update(value=image_paths, visible=True),
        gradio.update(value=json.dumps(debug_payload, ensure_ascii=False, indent=2)),
    )


def update_gallery_from_files_upload(files_value: Any):
    image_paths: List[str] = []
    raw = files_value
    if isinstance(files_value, list):
        for item in files_value:
            if isinstance(item, str):
                image_paths.append(item)
            elif isinstance(item, dict):
                candidate = (
                    item.get("path") or item.get("file_path") or item.get("name")
                )
                if isinstance(candidate, str):
                    image_paths.append(candidate)
    elif isinstance(files_value, str):
        image_paths = [files_value]
    debug_payload = {
        "raw": raw,
        "resolved_files_count": len(image_paths),
    }
    image_paths = [p for p in image_paths if _is_image_path(p)]
    return (
        gradio.update(value=image_paths, visible=True),
        gradio.update(value=json.dumps(debug_payload, ensure_ascii=False, indent=2)),
    )


def _is_image_path(p: str) -> bool:
    try:
        return Path(p).suffix.lower() in {
            ".jpg",
            ".jpeg",
            ".png",
            ".bmp",
            ".webp",
            ".tif",
            ".tiff",
        }
    except Exception:
        return False


def on_debug_toggle(flag: bool):
    try:
        state_manager.set_item("debug_enabled", bool(flag))
    except Exception:
        pass
    return (
        gradio.update(visible=bool(flag)),
        gradio.update(visible=bool(flag)),
        gradio.update(visible=bool(flag)),
    )


def on_gallery_select(
    evt: gradio.SelectData,
) -> Tuple[gradio.File, gradio.Textbox, gradio.Textbox]:
    # 当 Gallery 使用路径列表作为 value 时，evt.value 即选中的文件路径
    try:
        selected_path = evt.value  # type: ignore[attr-defined]
    except Exception:
        selected_path = None
    try:
        debug_text = json.dumps(
            {
                "index": getattr(evt, "index", None),
                "value": getattr(evt, "value", None),
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception:
        debug_text = str(evt)

    if isinstance(selected_path, str):
        path_str = selected_path
        state_manager.set_item("source_paths", [path_str])
        return (
            gradio.update(value=[path_str], visible=False),
            gradio.update(value=path_str),
            gradio.update(value=debug_text),
        )
    if isinstance(selected_path, dict):
        path = (
            selected_path.get("path")
            or selected_path.get("name")
            or selected_path.get("video", {}).get("path")
            or selected_path.get("image", {}).get("path")
        )
        if isinstance(path, str):
            state_manager.set_item("source_paths", [path])
            return (
                gradio.update(value=[path], visible=False),
                gradio.update(value=path),
                gradio.update(value=debug_text),
            )

    state_manager.clear_item("source_paths")
    return (
        gradio.update(value=None, visible=False),
        gradio.update(value=""),
        gradio.update(value=debug_text),
    )


def _extract_zip_to_temp(zip_path: str) -> str:
    try:
        base = Path(".temp/facefusion/upload_dirs")
        base.mkdir(parents=True, exist_ok=True)
        dst = base / uuid4().hex
        dst.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dst)
        return str(dst)
    except Exception:
        return ""


def pre_start() -> Tuple[gradio.File, gradio.Image, gradio.Button, gradio.Button]:
    return (
        gradio.File(visible=False),
        gradio.Image(visible=True),
        gradio.Button(visible=False),
        gradio.Button(visible=True),
    )


def pre_stop() -> Tuple[gradio.File, gradio.Image, gradio.Button, gradio.Button]:
    return (
        gradio.File(visible=False),
        gradio.Image(visible=False),
        gradio.Button(visible=True),
        gradio.Button(visible=False),
    )


def start(
    webcam_device_id: int,
    webcam_mode: WebcamMode,
    webcam_resolution: str,
    webcam_fps: Fps,
) -> Generator[VisionFrame, None, None]:
    state_manager.init_item("face_selector_mode", "one")
    state_manager.sync_state()

    camera_capture = get_local_camera_capture(webcam_device_id)
    stream = None

    if webcam_mode in ["udp", "v4l2"]:
        stream = open_stream(webcam_mode, webcam_resolution, webcam_fps)  # type:ignore[arg-type]
    webcam_width, webcam_height = unpack_resolution(webcam_resolution)

    if camera_capture and camera_capture.isOpened():
        camera_capture.set(cv2.CAP_PROP_FRAME_WIDTH, webcam_width)
        camera_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, webcam_height)
        camera_capture.set(cv2.CAP_PROP_FPS, webcam_fps)

        for capture_frame in multi_process_capture(camera_capture, webcam_fps):
            capture_frame = cv2.cvtColor(capture_frame, cv2.COLOR_BGR2RGB)
            # 写入监视器缓存文件，供 MJPEG 路由使用
            try:
                save_latest_frame(capture_frame)
            except Exception:
                pass

            if webcam_mode == "inline":
                yield capture_frame
            else:
                try:
                    stream.stdin.write(capture_frame.tobytes())
                except Exception:
                    pass


def stop() -> gradio.Image:
    clear_camera_pool()
    return gradio.Image(value=None)
