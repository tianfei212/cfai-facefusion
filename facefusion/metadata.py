from typing import Optional

METADATA = {
    "name": "中影人工智能研究院",
    "description": "Industry leading face manipulation platform",
    "version": "",
    "license": "OpenRAIL-AS",
    "author": "Junk Warrior",
    "url": "",
}


def get(key: str) -> Optional[str]:
    if key in METADATA:
        return METADATA.get(key)
    return None
