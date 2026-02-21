import json
from django import template

register = template.Library()

@register.filter
def json_dumps(value):
    """Красивый JSON из Python-объекта."""
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except Exception:
        return str(value)

@register.filter
def dict_get(d, key):
    """Получить значение из словаря по ключу в шаблоне."""
    try:
        return d.get(key, 0)
    except Exception:
        return 0
