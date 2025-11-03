from typing import Optional

METADATA =\
{
	'name': 'FaceFusionFree',
	'description': 'Industry leading face manipulation platform',
	'version': '3.9.1',
	'license': 'OpenRAIL-AS',
	'author': 'Henry Ruhs',
	'url': 'http://www.wangzhifeng.vip'
}


def get(key : str) -> Optional[str]:
	if key in METADATA:
		return METADATA.get(key)
	return None
