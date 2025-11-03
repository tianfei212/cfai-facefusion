#!/usr/bin/env python3
import os
import time
import pyfiglet


# 清屏（可选）
os.system("cls" if os.name == "nt" else "clear")

# 标题大字
big_text = pyfiglet.figlet_format("FaceFusionFree", font="slant")

# 构建展示块
banner = ""

print()
print(banner)
print("\n" + "═" * 80 + "\n")
time.sleep(5)

os.environ["OMP_NUM_THREADS"] = "1"

from facefusion import core

if __name__ == "__main__":
    core.cli()
