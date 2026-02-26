import sys
sys.path.insert(0, '.')
import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
import django
django.setup()

import requests, json
from edi.services import DocrobotClient

client = DocrobotClient()

doc_id = '287d6c05-1239-11f1-a66a-86b0bd7f7022'
headers = client._api_headers()
headers['gln'] = str(client.gln)

url = f'{client.API_URL}/api/v1/documents/folders/inbox/docGroup/EDI/docTypes/ORDER/document/{doc_id}'
r = requests.get(url, headers=headers, timeout=15)
data = r.json()
print(f"HTTP {r.status_code}")
print(f"Ключи ответа: {list(data.keys())}")
print(f"has content: {bool(data.get('content'))}")
print(f"content length: {len(data.get('content', ''))}")
print(json.dumps({k: v for k, v in data.items() if k != 'content'}, ensure_ascii=False, indent=2))
