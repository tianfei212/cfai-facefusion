import gradio as gr
from typing import Optional
from pathlib import Path
import json

from facefusion import logger
from facefusion.obs_integration import (
    change_heibai_state,
    create_client,
    disconnect_client,
    update_first_browser_source_url,
    update_first_video_source_file,
    default_mjpeg_url,
)
import obsws_python as obs


_client: Optional[obs.ReqClient] = None  # type: ignore

SETTINGS_PATH = Path(".temp/facefusion/obs_settings.json")


def _load_settings() -> dict:
    default = {
        "host": "127.0.0.1",
        "port": 4455,
        "password": "",
        "url": default_mjpeg_url(),
    }
    try:
        if SETTINGS_PATH.exists():
            with SETTINGS_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
                default.update(
                    {
                        "host": data.get("host", default["host"]),
                        "port": int(data.get("port", default["port"])),
                        "password": data.get("password", default["password"]),
                        "url": data.get("url", default["url"]),
                    }
                )
    except Exception:
        # 保持简洁：读取失败则回退默认
        pass
    return default


def _save_settings(host: str, port: int, password: str, url: str) -> None:
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with SETTINGS_PATH.open("w", encoding="utf-8") as f:
            json.dump(
                {"host": host, "port": int(port), "password": password, "url": url},
                f,
                ensure_ascii=False,
                indent=2,
            )
    except Exception:
        # 简化异常：保存失败不抛出到 UI
        pass


def _do_connect(host: str, port: int, password: str, url: str) -> str:
    global _client
    try:
        _client = create_client(host, port, password)
        _save_settings(host, port, password, url)
        return "✅ 连接成功"
    except Exception as e:
        _client = None
        return f"❌ 连接失败：{e}"


def _do_disconnect() -> str:
    global _client
    disconnect_client(_client)
    _client = None
    return "ℹ️ 已断开连接"


def _do_bind(url: str) -> str:
    if _client is None:
        return "❌ 未连接 OBS"
    try:
        ok = update_first_browser_source_url(_client, url)
        # 绑定成功也保存当前 URL（保持与连接参数一致的持久化）
        try:
            if SETTINGS_PATH.exists():
                data = _load_settings()
                _save_settings(
                    data.get("host", "127.0.0.1"),
                    int(data.get("port", 4455)),
                    data.get("password", ""),
                    url,
                )
        except Exception:
            pass
        return (
            "✅ 已绑定到第一个浏览器源" if ok else "❌ 未找到浏览器源（browser_source）"
        )
    except Exception as e:
        return f"❌ 绑定失败：{e}"


def _do_save(host: str, port: int, password: str, url: str) -> str:
    _save_settings(host, port, password, url)
    return "✅ 已保存设置"


def _change_bw() -> str:
    if _client is None:
        return "❌ 未连接 OBS"
    ok = change_heibai_state(_client)
    if ok is None:
        return "❌ 更新出错"
    return "✅ 已应用黑白效果" if ok else "✅ 已关闭黑白效果"


def render() -> None:
    with gr.Accordion("OBS 控制", open=True) as obs_accordion:
        settings = _load_settings()
        with gr.Row():
            host = gr.Textbox(label="Host", value=settings["host"], scale=2)
            port = gr.Number(label="Port", value=settings["port"], precision=0, scale=1)
            password = gr.Textbox(
                label="Password", type="password", value=settings["password"], scale=2
            )

        with gr.Row():
            url = gr.Textbox(label="URL", value=settings["url"], scale=3)

        with gr.Row():
            btn_connect = gr.Button("连接 OBS", variant="primary")
            btn_disconnect = gr.Button("断开连接")
            btn_bind = gr.Button("绑定 MJPEG 到第一个浏览器源", variant="primary")
            btn_save = gr.Button("保存设置")

        status = gr.Markdown(
            "建议先点击 Start Webcam 再绑定 MJPEG。\n依赖：`./python.link -m pip install obsws-python`"
        )

        btn_connect.click(
            _do_connect, inputs=[host, port, password, url], outputs=status
        )
        btn_disconnect.click(_do_disconnect, inputs=None, outputs=status)
        btn_bind.click(_do_bind, inputs=[url], outputs=status)
        btn_save.click(_do_save, inputs=[host, port, password, url], outputs=status)

        # —— 彩色变黑白（迁移按钮） ——
        with gr.Row():
            bw_btn = gr.Button("🎚️ 开启/关闭黑白效果", variant="secondary")

        bw_btn.click(_change_bw, outputs=status)

        # 页面加载时自动从持久化文件填充（解决刷新后丢失的问题）
        def _do_load():
            s = _load_settings()
            return s["host"], int(s["port"]), s["password"], s["url"]

        # Gradio v5 页面加载事件：刷新时自动填充值
        # gr.on(triggers=[gr.PageLoad], fn=_do_load, inputs=None, outputs=[host, port, password, url])

        # —— B 阶段：迁移假工程的背景视频控制界面到此面板 ——
        def _get_video_files() -> list[str]:
            bgs_path = Path("fake_facefusion/bgs")
            if not bgs_path.exists():
                return []
            video_extensions = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".webm"}
            files: list[str] = []
            for fp in bgs_path.rglob("*"):
                if fp.is_file() and fp.suffix.lower() in video_extensions:
                    files.append(str(fp.absolute()))
            return files

        with gr.Row():
            gr.Markdown("## 背景视频控制（迁移自 fake_facefusion/gradio_demo.py）")

        with gr.Row():
            gallery = gr.Gallery(
                value=_get_video_files(),
                label="选择视频文件",
                show_label=True,
                columns=4,
                rows=3,
                height="auto",
                object_fit="contain",
                allow_preview=True,
            )
            video_result = gr.Textbox(label="操作结果", interactive=False)

        with gr.Row():
            refresh_btn = gr.Button("🔄 刷新视频列表", variant="secondary")
            refresh_result = gr.Textbox(label="刷新结果", interactive=False)

        def _on_video_select(evt: gr.SelectData) -> str:
            try:
                if _client is None:
                    return "❌ 未连接 OBS"
                selected = evt.value
                file_path: Optional[str] = None
                if isinstance(selected, str):
                    file_path = selected
                elif isinstance(selected, dict):
                    # 兼容多种返回结构
                    file_path = (
                        selected.get("video", {}).get("path")
                        or selected.get("path")
                        or selected.get("name")
                    )
                if not file_path:
                    return "❌ 未解析所选视频路径"
                ok = update_first_video_source_file(_client, file_path)
                if ok:
                    return f"✅ 成功更新 OBS 视频源: {Path(file_path).name}"
                else:
                    return "❌ 更新失败：未找到 ffmpeg_source 类型的媒体源"
            except Exception as e:
                return f"❌ 错误：{e}"

        def _refresh_videos():
            files = _get_video_files()
            return files, ("✅ 视频列表已刷新" if files else "⚠️ 未找到视频文件")

        gallery.select(fn=_on_video_select, outputs=video_result)
        refresh_btn.click(fn=_refresh_videos, outputs=[gallery, refresh_result])


def listen() -> None:
    # Phase A：无全局事件监听，交互已在 render 内绑定。
    pass
