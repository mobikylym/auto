import random
from typing import Literal
import httpx
import yaml
import re
import time
import json
from jsonpath_ng.ext import parse


def load_config(config_path='config.yaml'):
    with open(config_path, 'r') as file:
        conf = yaml.safe_load(file)
    return conf


config = load_config()


def get_session(
    server: str = config.get('mgmt', {}).get('server'),
    username: str = config.get('mgmt', {}).get('username', 'admin'),
    password: str = config.get('mgmt', {}).get('password', 'admin'),
    is_mgmt_server: bool = True
) -> httpx.Client:
    if server is None:
        raise ValueError('Server must be defined.')

    base_url = f'https://{server}/'
    login_url = 'management/authenticate' if is_mgmt_server else 'slave/authenticate'

    client = httpx.Client(base_url=base_url, verify=False)

    start_time = time.time()
    timeout = 3 * 60
    retry_delay = 15

    while True:
        try:
            response = client.post(login_url, json={"username": username, "password": password})
            if response.status_code == 401:
                wait_time = random.uniform(1, 5)
                time.sleep(wait_time)
                response = client.post(login_url, json={"username": username, "password": password})
            response.raise_for_status()

            token = response.json().get("token")
            if not token:
                raise ValueError("Token not found in the response.")

            client.headers.update({"Authorization": f"{token}"})
            return client

        except Exception as ex:
            if time.time() - start_time > timeout:
                raise Exception(f'Timeout reached: the server is unavailable for {timeout / 60} minutes.') from ex
            print(f'Error: {ex}. Retry after {retry_delay} seconds...')
            time.sleep(retry_delay)


def get_apikey(
    session: httpx.Client,
    key_label: str
):
    start_time = time.time()
    timeout = 3 * 60
    retry_delay = 15

    while True:
        try:
            response = session.get(f'management/auth_settings/api_keys')
            response.raise_for_status()

            pattern = re.compile(rf'"label":\s*"{key_label}"')
            match = pattern.search(response.text)

            if match:
                response = session.post(f'management/auth_settings/api_keys/revoke', json={"label": f"{key_label}"})
                response.raise_for_status()

            response = session.post(f'management/auth_settings/api_keys/create', json={"label": f"{key_label}"})
            response.raise_for_status()

            return response.json().get('value')

        except Exception as ex:
            if time.time() - start_time > timeout:
                raise Exception(f'Timeout reached: the server is unavailable for {timeout / 60} minutes.') from ex
            print(f'Error: {ex}. Retry after {retry_delay} seconds...')
            time.sleep(retry_delay)


def any_keys_exist(data, keys_to_check):
    """
    Проверяет, присутствует ли хотя бы один конечный ключ из keys_to_check в data, игнорируя значения.
    Возвращает True, если хотя бы один ключ существует; иначе — False.
    """
    for key, value in keys_to_check.items():
        if isinstance(value, dict):
            if key in data and isinstance(data[key], dict) and any_keys_exist(data[key], value):
                return True
        else:
            if key in data:
                return True
    return False


def all_keys_match(data, keys_to_check):
    """
    Проверяет, присутствуют ли все ключи и значения из keys_to_check в data.
    Преобразует все значения к строкам в нижнем регистре перед сравнением.
    Возвращает True, если все ключи и значения совпадают; иначе — False.
    """
    for key, value in keys_to_check.items():
        if isinstance(value, dict):
            if key not in data or not isinstance(data[key], dict) or not all_keys_match(data[key], value):
                return False
        else:
            actual_value = str(data.get(key, None)).lower()
            expected_value = str(value).lower()
            if actual_value != expected_value:
                return False
    return True


def deep_update(source, updates):
    if source is None:
        source = {}

    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(source.get(key), dict):
            deep_update(source[key], value)
        else:
            source[key] = value


def delete_key(data, key_paths):
    keys = key_paths.split('.')
    for key in keys[:-1]:
        data = data.get(key, {})
        if not isinstance(data, dict):
            return
    data.pop(keys[-1], None)


def check_json_path(
    json_data: dict | list,
    key_path: str
) -> bool:
    """
    Проверка наличия ключа в JSON-ответе по пути (например, 'data.items').\n
    Возвращает True, если хотя бы 1 указанный элемент найден, и False, если нет.
    """
    jsonpath_expr = parse(key_path)
    matches = jsonpath_expr.find(json_data)
    return len(matches) > 0


def get_json_count(
    json_data: dict | list,
    key_path: str
) -> int:
    """
    Подсчет количества элементов в JSON-массиве по указанному пути.\n
    Возвращает количество найденных элементов. Если не найдено ни одного - возвращает 0.
    """
    jsonpath_expr = parse(key_path)
    matches = jsonpath_expr.find(json_data)
    if matches and isinstance(matches[0].value, list):
        return len(matches[0].value)
    return 0


def get_json_value(
    json_data: dict | list,
    key_path: str
) -> str | None:
    """
    Получение значения атрибута по указанному JSON-пути.\n
    Возвращает значение найденного элемента либо None.
    """
    jsonpath_expr = parse(key_path)
    matches = jsonpath_expr.find(json_data)
    return matches[0].value if matches else None


def check_regex(
    json_data: dict | list,
    regex: str
) -> bool:
    """
    Проверка наличия ключа в тексте ответа по регулярному выражению.\n
    Возвращает True, если хотя бы 1 указанный элемент найден, и False, если нет.
    """
    response_text = json.dumps(json_data)
    return bool(re.search(regex, response_text))


def get_regex_count(
    json_data: dict | list,
    regex: str
) -> int:
    """
    Подсчёт количества совпадений в тексте ответа по регулярному выражению.\n
    Возвращает количество найденных элементов. Если не найдено ни одного - возвращает 0.
    """
    response_text = json.dumps(json_data)
    matches = re.findall(regex, response_text)
    return len(matches)


def get_regex_value(
    json_data: dict | list,
    regex: str,
    match_number: int = 1
) -> str | None:
    """
    Получение значения из первой группы по регулярному выражению и номеру совпадения.\n
    Возвращает значение найденного элемента либо None.
    """
    response_text = json.dumps(json_data)
    matches = re.finditer(regex, response_text)
    for i, match in enumerate(matches, start=1):
        if i == match_number:
            return match.group(1)
    return None


def check_required_fields(
    json_data: dict | list,
    required_fields: list
) -> bool:
    """
    Проверка наличия обязательных полей в теле ответа.\n
    Возвращает True только если все перечисленные ключи присутствуют в теле ответа на любом уровне вложенности.
    """
    response_text = json.dumps(json_data)
    return all(re.search(rf'"{field}":', response_text) for field in required_fields)


def check_unique_value(
    json_data: dict | list,
    path: str
) -> bool:
    """
    Проверка уникальности значений по ключу, указанному в виде пути в строке (например, 'data.items.id' - последним
    должен быть указан ключ внутри элемента массива. В нашем случае массив 'items').\n
    Работает со всеми уровнями вложенности. Если конечный массив 'items' вложен в другой массив, то в строке
    прописывается индекс элемента этого массива (например, 'data[0].items.id')\n
    Возвращает True только если все значения указанного ключа уникальны внутри массива, иначе False.
    """
    keys = path.split('.')
    data_element = json_data

    for i, key in enumerate(keys):

        if '[' in key and ']' in key:
            key_name, index = key.split('[')
            index = int(index[:-1])

            if key_name in data_element and isinstance(data_element[key_name], list):
                data_element = data_element[key_name][index]
            else:
                return False
        else:
            if key in data_element:
                data_element = data_element[key]
            else:
                return False

        if i == len(keys) - 2 and isinstance(data_element, list):
            last_key = keys[-1]
            ids = [item.get(last_key) for item in data_element if last_key in item]
            return len(ids) == len(set(ids))

    return False


def wait_for_element_in_response(
    session: httpx.Client,
    url: str,
    key: str,
    value: str | int | float | bool | list | dict = None,
    request_method: Literal['GET', 'POST', 'PUT', 'PATCH', 'DELETE'] = 'GET',
    timeout: int = 20,
    retry_delay: float = 2.0,
    params: dict = None,
    data: dict = None,
) -> bool:
    """
    Ожидание появления элемента в ответе с проверкой пары ключ-значение и повторными запросами.\n
    Если value не передан, проверяется только наличие ключа в ответе. Путь к key прописывается от корня (pageable.sort.empty)\n
    Возвращает True, если за время timeout появляется указанный ключ с его значением (если value передан).
    """
    start_time = time.time()

    while time.time() - start_time < timeout:
        response = session.request(
            method=request_method.upper(),
            url=url,
            params=params,
            json=data,
        )
        response.raise_for_status()

        try:
            response_json = response.json()

            if value is not None:
                if get_json_value(response_json, key) == value:
                    return True
            else:
                if check_json_path(response_json, key):
                    return True

        except ValueError:
            pass

        time.sleep(retry_delay)

    return False
