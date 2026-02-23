"""
Запуск: python fix_templates.py
Исправляет все HTML-шаблоны — добавляет {% load edi_tags %} там где нужно.
"""
import os

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), 'edi', 'templates', 'edi')

# Шаблоны которые используют фильтры dict_get / json_dumps
NEEDS_EDI_TAGS = ['dashboard.html', 'document_detail.html']

for filename in os.listdir(TEMPLATES_DIR):
    if not filename.endswith('.html'):
        continue

    filepath = os.path.join(TEMPLATES_DIR, filename)
    content = open(filepath, encoding='utf-8').read()

    # Убираем кривые варианты если попали
    content = content.replace('{%% load edi_tags %%}\n', '')
    content = content.replace('{%% load edi_tags %%}', '')

    # Для нужных шаблонов добавляем правильный тег после extends
    if filename in NEEDS_EDI_TAGS:
        if '{% load edi_tags %}' not in content:
            content = content.replace(
                "{% extends 'edi/base.html' %}",
                "{% extends 'edi/base.html' %}\n{% load edi_tags %}"
            )
            print(f'✓ Добавлен load edi_tags в {filename}')
        else:
            print(f'  {filename} — уже содержит load edi_tags')
    else:
        # Для остальных просто убедимся что нет мусора
        if '{%%' in content:
            print(f'✓ Убран мусор из {filename}')
        else:
            print(f'  {filename} — OK')

    open(filepath, 'w', encoding='utf-8').write(content)

print('\nГотово! Перезапустите сервер.')
