"""
监视器集成（monitor_integration）

用途概述：
- 将 Webcam 捕获到的 RGB 帧转存为 JPEG 文件 `latest.jpg`，目录为 `.temp/monitor`；
- 提供一个简单的 MJPEG（multipart/x-mixed-replace）生成器，从 `latest.jpg` 持续读取并推流；
- 在 Gradio 所使用的 FastAPI/Starlette 应用上挂载路由（默认 `/monitor/mjpeg`），供浏览器或 OBS 订阅。

设计要点：
- 直接复用底层 ASGI 应用以挂载路由，脱耦于 Gradio 的内部实现；
- 写文件与读取流尽量不抛异常，避免影响 UI 的采集循环与用户体验；
- `frame_interval_sec` 控制推流帧间隔，可根据磁盘 I/O 与画面刷新需求做权衡。
"""

import os
import asyncio
from typing import Optional, AsyncGenerator

import cv2
from starlette.responses import StreamingResponse

from facefusion import logger, state_manager
from facefusion.filesystem import create_directory, is_file


def _monitor_dir_path() -> str:
    # 监视器缓存目录：优先使用 state_manager 中的临时目录；
    # 若未初始化（None），则回落到当前工作目录。
    temp_root = state_manager.get_item("temp_path") or os.getcwd()
    return os.path.join(temp_root, "monitor")


def _monitor_file_path() -> str:
    # `latest.jpg` 的完整路径，用作 MJPEG 数据源。
    return os.path.join(_monitor_dir_path(), "latest.jpg")


def ensure_monitor_dir() -> bool:
    # 确保监视器目录存在；若创建失败，返回 False。
    try:
        return create_directory(_monitor_dir_path())
    except Exception:
        return False


def save_latest_frame(frame) -> None:
    """
    将 RGB 帧保存为 `.temp/monitor/latest.jpg`（JPEG 格式）。

    使用说明：
    - 输入 `frame` 期望为 RGB（与 Webcam 捕获循环保持一致）；
    - 为适配 OpenCV 的 JPEG 编码，先转换为 BGR；
    - 内部异常被吞噬并打到 debug 日志，避免打断采集循环。

    Notes (English):
    - Input frame is expected in RGB (as produced by webcam capture loop).
    - Converts to BGR for OpenCV JPEG encoding.
    - Silently ignores errors to avoid breaking the capture loop.
    """
    try:
        ensure_monitor_dir()
        # OpenCV 的大多数图像处理 API 以 BGR 为默认通道顺序；
        # 因此先将 RGB 转换为 BGR。
        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        # 将图像编码为 JPEG 二进制缓存。
        ok, buf = cv2.imencode(".jpg", bgr)
        if not ok:
            return
        # 将编码后的数据写入 `latest.jpg`。
        with open(_monitor_file_path(), "wb") as f:
            f.write(buf.tobytes())
    except Exception as e:
        logger.debug(f"[monitor_integration] save_latest_frame failed: {e}", __name__)


async def _mjpeg_generator(frame_interval_sec: float = 0.04) -> AsyncGenerator[bytes, None]:
    # MJPEG 边界标识；浏览器/OBS 会根据该边界解析多帧 JPEG。
    boundary = b"--frame"
    while True:
        try:
            file_path = _monitor_file_path()
            if is_file(file_path):
                try:
                    # 每一轮从磁盘读取最新的 JPEG，再按 MJPEG 规范拼接响应块：
                    # --frame\r\n
                    # Content-Type: image/jpeg\r\n\r\n
                    # <JPEG BYTES>\r\n
                    with open(file_path, "rb") as f:
                        jpg = f.read()
                    yield boundary + b"\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
                except Exception as e:
                    logger.debug(f"[monitor_integration] read latest.jpg failed: {e}", __name__)
            # 控制帧间隔，避免频繁读取造成 I/O 压力。
            await asyncio.sleep(frame_interval_sec)
        except Exception as e:
            logger.error(f"[monitor_integration] mjpeg generator error: {e}", __name__)
            await asyncio.sleep(frame_interval_sec)


def mount(app, route_path: str = "/monitor/mjpeg", frame_interval_sec: float = 0.04) -> None:
    """
    在 Gradio 使用的 FastAPI/Starlette 应用上挂载 MJPEG 路由。

    参数：
    - app：ASGI 应用实例（FastAPI 或 Starlette），从 Gradio Blocks 的 `app` 字段获取；
    - route_path：路由路径（默认为 `/monitor/mjpeg`）；
    - frame_interval_sec：推流帧间隔（秒）。
    """

    async def _monitor_mjpeg(_request=None):
        return StreamingResponse(
            _mjpeg_generator(frame_interval_sec),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    try:
        # FastAPI 与 Starlette 的路由注册方法略有不同，分别适配：
        if hasattr(app, "add_api_route"):
            app.add_api_route(route_path, _monitor_mjpeg, methods=["GET"])  # FastAPI
        else:
            app.add_route(route_path, _monitor_mjpeg, methods=["GET"])  # Starlette
        logger.info(f"[monitor_integration] mounted MJPEG route: {route_path}", __name__)
    except Exception as e:
        logger.error(f"[monitor_integration] failed to mount MJPEG route: {e}", __name__)