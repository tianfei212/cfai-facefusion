import gradio as gr
from typing import Optional
from pathlib import Path
import json

from facefusion import logger
from facefusion.obs_integration import (
    create_client,
    disconnect_client,
    update_first_browser_source_url,
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
                default.update({
                    "host": data.get("host", default["host"]),
                    "port": int(data.get("port", default["port"])),
                    "password": data.get("password", default["password"]),
                    "url": data.get("url", default["url"]),
                })
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
                _save_settings(data.get("host", "127.0.0.1"), int(data.get("port", 4455)), data.get("password", ""), url)
        except Exception:
            pass
        return "✅ 已绑定到第一个浏览器源" if ok else "❌ 未找到浏览器源（browser_source）"
    except Exception as e:
        return f"❌ 绑定失败：{e}"


def _do_save(host: str, port: int, password: str, url: str) -> str:
    _save_settings(host, port, password, url)
    return "✅ 已保存设置"


def render() -> None:
    with gr.Accordion("OBS 控制", open=True) as obs_accordion:
        settings = _load_settings()
        with gr.Row():
            host = gr.Textbox(label="Host", value=settings["host"], scale=2)
            port = gr.Number(label="Port", value=settings["port"], precision=0, scale=1)
            password = gr.Textbox(label="Password", type="password", value=settings["password"], scale=2)

        with gr.Row():
            url = gr.Textbox(label="URL", value=settings["url"], scale=3)

        with gr.Row():
            btn_connect = gr.Button("连接 OBS", variant="primary")
            btn_disconnect = gr.Button("断开连接")
            btn_bind = gr.Button("绑定 MJPEG 到第一个浏览器源", variant="primary")
            btn_save = gr.Button("保存设置")

        status = gr.Markdown("建议先点击 Start Webcam 再绑定 MJPEG。\n依赖：`./python.link -m pip install obsws-python`")

        btn_connect.click(_do_connect, inputs=[host, port, password, url], outputs=status)
        btn_disconnect.click(_do_disconnect, inputs=None, outputs=status)
        btn_bind.click(_do_bind, inputs=[url], outputs=status)
        btn_save.click(_do_save, inputs=[host, port, password, url], outputs=status)

        # 页面加载时自动从持久化文件填充（解决刷新后丢失的问题）
        def _do_load():
            s = _load_settings()
            return s["host"], int(s["port"]), s["password"], s["url"]

        # gr.on(triggers=[obs_accordion.], fn=_do_load, inputs=None, outputs=[host, port, password, url])


def listen() -> None:
    # Phase A：无全局事件监听，交互已在 render 内绑定。
    pass