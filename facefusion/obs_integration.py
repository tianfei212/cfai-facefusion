"""
基于 obsws-python 的标准 OBS WebSocket 集成。

目标：
- 仅使用 obsws-python 官方提供的 ReqClient 标准 API；
- 提供与 fake_facefusion/obs.py 一致的接口风格；
- 简化异常处理，不做额外环境防御或冗余检查。
"""

from pathlib import Path
from typing import Optional

import obsws_python as obs


def create_client(host: str, port: int, password: str) -> obs.ReqClient:
    """创建并返回 obsws-python 的同步请求客户端。"""
    client = obs.ReqClient(host=host, port=port, password=password)
    return client


def disconnect_client(client: Optional[obs.ReqClient]) -> None:
    """断开并清理客户端（若已连接）。"""
    if client is not None:
        try:
            client.disconnect()
        except Exception:
            # 简化异常处理：忽略断开异常
            pass


def update_first_video_source_file(
    client: obs.ReqClient, new_file_path: str, reinitialize: bool = True
) -> bool:
    """
    更新第一个 ffmpeg_source 输入的本地文件路径。
    与 fake_facefusion/obs.py 保持完全一致的接口与行为。
    """
    response = client.get_input_list(kind="ffmpeg_source")
    inputs = response.inputs
    video_abs_path = str(Path(new_file_path).absolute())

    if inputs:
        input_name = inputs[0]["inputName"]
        client.set_input_settings(
            name=input_name,
            settings={"local_file": video_abs_path},
            overlay=reinitialize,
        )
        return True
    return False


def update_first_browser_source_url(
    client: obs.ReqClient, url: str, reinitialize: bool = True
) -> bool:
    """
    更新第一个 browser_source 输入的 URL 设置。
    调用 obsws-python 标准 API：get_input_list + set_input_settings。
    """
    response = client.get_input_list(kind="ffmpeg_source")
    inputs = response.inputs
    if inputs:
        input_name = inputs[-1]["inputName"]
        client.set_input_settings(
            name=input_name,
            settings={"input": url, "is_local_file": False},
            overlay=reinitialize,
        )
        return True
    return False


def default_mjpeg_url() -> str:
    """
    返回默认的 MJPEG 路由地址（与当前项目集成保持一致）。
    可在后续阶段做端口与路径的自动探测或配置化。
    """
    return "http://127.0.0.1:7860/monitor/mjpeg"

def change_heibai_state(client: obs.ReqClient) -> bool|None:
    """
    遍历所有输入源，查找名为“黑白”的滤镜，将其启用状态取反。
    如果该滤镜当前是启用的，则禁用；如果禁用，则启用。
    """
    input_response = client.get_input_list()

    for input_info in input_response.inputs:
        input_name = input_info["inputName"]

        final_enabled = None
        try:
            # 获取该输入源的所有滤镜
            filters_response = client.get_source_filter_list(name=input_name)
            for f in filters_response.filters:
                if f["filterName"] == "黑白":
                    # 当前启用状态
                    enabled = f["filterEnabled"]
                    # 切换启用状态
                    client.set_source_filter_enabled(
                        source_name=input_name,
                        filter_name="黑白",
                        enabled=not enabled
                    )
                    final_enabled = not enabled
            return final_enabled
        except obs.error.OBSSDKError:
            return None