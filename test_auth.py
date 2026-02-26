# test_auth.py — проверка авторизации Docrobot API
import requests
import json

API_URL = 'https://edi-api.docrobot.kz'
USERNAME = 'Food_Factory'  # Замени на свой логин
PASSWORD = 'your_password'  # Замени на свой пароль
GLN = '9845000099712'


def test_auth():
    print("=== Тест 1: Получение токена ===")
    resp = requests.post(
        f'{API_URL}/api/v1/auth',
        json={'login': USERNAME, 'password': PASSWORD},
        headers={'Content-Type': 'application/json'},
        timeout=15,
    )
    print(f"Status: {resp.status_code}")
    data = resp.json()
    print(f"Response: {json.dumps(data, indent=2, ensure_ascii=False)}")

    token = data.get('token')
    if not token:
        print("❌ Токен не получен!")
        return

    print(f"\n=== Тест 2: Запрос документов (токен в заголовке) ===")
    # Вариант A: Токен как есть (как в моём коде)
    headers_a = {
        'Authorization': token,
        'Accept': 'application/json',
    }
    params = {
        'gln': GLN,
        'docDateFrom': '25-01-2026',
        'docDateTo': '24-02-2026',
        'page': 0,
        'pageSize': 10,
    }

    resp_a = requests.get(
        f'{API_URL}/api/v1/documents/folders/inbox/docGroup/EDI/docTypes/ORDER',
        headers=headers_a,
        params=params,
        timeout=30,
    )
    print(f"Вариант A (Authorization: {token[:20]}...): {resp_a.status_code}")
    if resp_a.status_code != 200:
        print(f"Error: {resp_a.text[:200]}")

    # Вариант B: Bearer префикс
    print(f"\n=== Тест 3: Запрос документов (Bearer префикс) ===")
    headers_b = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
    }
    resp_b = requests.get(
        f'{API_URL}/api/v1/documents/folders/inbox/docGroup/EDI/docTypes/ORDER',
        headers=headers_b,
        params=params,
        timeout=30,
    )
    print(f"Вариант B (Authorization: Bearer {token[:20]}...): {resp_b.status_code}")
    if resp_b.status_code == 200:
        data = resp_b.json()
        print(f"✅ Успех! Найдено документов: {len(data.get('items', []))}")
    else:
        print(f"Error: {resp_b.text[:200]}")


if __name__ == '__main__':
    test_auth()