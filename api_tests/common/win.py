import re
import sys
from typing import Literal
import yaml
import winrm
from api_tests.common import base
from jinja2 import Environment, FileSystemLoader


def render_template(template_name, context):
    env = Environment(loader=FileSystemLoader('templates'))  # Возможно нужно будет изменить на "api_tests/common/templates"
    template = env.get_template(template_name)
    return template.render(context)


def load_config(config_path='config.yaml'):
    with open(config_path, 'r') as file:
        conf = yaml.safe_load(file)
    return conf


config = load_config()


def get_winrm_connection(
    server: str,
    username: str = config.get('win', {}).get('username', 'Administrator'),
    password: str = config.get('win', {}).get('password', 'Logaribe2*'),
    port: int = 5985
) -> winrm.Session:
    try:
        session = winrm.Session(f'http://{server}:{port}/wsman', auth=(username, password), transport='ntlm')

        result = session.run_cmd('echo test')
        if result.status_code != 0:
            raise Exception(f'Failed to execute command on server {server}, status code: {result.status_code}')

        return session

    except Exception as ex:
        print(f'Failed to get WinRM connection with server IP "{server}": {ex}')
        sys.exit(1)


def check_config(
    winrm_session: winrm.Session,
    expected_config: dict,
    file_path: str = config.get('win', {}).get('config_file_path', 'C:/Program Files (x86)/Xello/SlaveServer/external.yml'),
    expect_absence: bool = False
) -> bool:
    """
    Проверяет наличие или отсутствие всех ключей из expected_config в конфигурационном файле.
    Если expect_absence == True, проверяет, что все ключи отсутствуют (игнорируя значения).
    Если expect_absence == False, проверяет, что все ключи присутствуют с правильными значениями.
    Возвращает True, если условие выполнено, иначе — False.
    """
    check_command = f'Test-Path "{file_path}"'
    response = winrm_session.run_ps(check_command)
    file_exists = str(response.std_out.strip().lower()) in ["true", "b'true'"]

    if file_exists:
        command = f'type "{file_path}"'
        response = winrm_session.run_ps(command)
        if response.status_code != 0:
            raise Exception(f"Failed to read file: {response.std_err.decode()}")
    else:
        return False

    file_content = response.std_out.decode()
    config_data = yaml.safe_load(file_content) if file_content else {}

    if expect_absence:
        return not base.any_keys_exist(config_data, expected_config)
    else:
        return base.all_keys_match(config_data, expected_config)


def update_config(
    winrm_session: winrm.Session,
    new_config: dict,
    file_path: str = config.get('win', {}).get('config_file_path', 'C:/Program Files (x86)/Xello/SlaveServer/external.yml')
) -> bool:
    """
    Обновляет конфигурационный файл, добавляя или изменяя параметры на основе new_config.
    Возвращает True, если все ключи и значения удалось обновить, иначе — False.
    """
    check_command = f'Test-Path "{file_path}"'
    response = winrm_session.run_ps(check_command)
    file_exists = str(response.std_out.strip().lower()) in ["true", "b'true'"]

    if file_exists:
        command = f'type "{file_path}"'
        response = winrm_session.run_ps(command)
        if response.status_code != 0:
            raise Exception(f"Failed to read file: {response.std_err.decode()}")
        file_content = response.std_out.decode()
    else:
        file_content = ""

    config_data = yaml.safe_load(file_content) if file_content else {}
    base.deep_update(config_data, new_config)

    updated_yaml = yaml.dump(config_data, default_flow_style=False)
    updated_yaml = re.sub(r'\'(\d+|true|false)\'', r'\1', updated_yaml)

    command = f'Set-Content -Path "{file_path}" -Value @\"\n{updated_yaml}\"@'
    response = winrm_session.run_ps(command)
    if response.status_code != 0:
        raise Exception(f"Failed to write file: {response.std_err.decode()}")

    return check_config(winrm_session, new_config, file_path)


def delete_config(
    winrm_session: winrm.Session,
    keys_to_delete: list[str],
    file_path: str = config.get('win', {}).get('config_file_path', 'C:/Program Files (x86)/Xello/SlaveServer/external.yml')
) -> bool:
    """
    Удаляет из конфигурационного файла ключи, указанные в keys_to_delete.
    Возвращает True, если все указанные ключи были удалены, иначе — False.
    """
    check_command = f'Test-Path "{file_path}"'
    response = winrm_session.run_ps(check_command)
    file_exists = str(response.std_out.strip().lower()) in ["true", "b'true'"]

    if file_exists:
        command = f'type "{file_path}"'
        response = winrm_session.run_ps(command)
        if response.status_code != 0:
            raise Exception(f"Failed to read file: {response.std_err.decode()}")
        file_content = response.std_out.decode()
    else:
        create_command = f'New-Item -Path "{file_path}" -ItemType File'
        response = winrm_session.run_ps(create_command)
        if response.status_code != 0:
            raise Exception(f"Failed to create file: {response.std_err.decode()}")

        return True

    config_data = yaml.safe_load(file_content) if file_content else {}

    for key_path in keys_to_delete:
        base.delete_key(config_data, key_path)

    updated_yaml = yaml.dump(config_data, default_flow_style=False)
    updated_yaml = re.sub(r'\'(\d+|true|false)\'', r'\1', updated_yaml)
    if str(updated_yaml).strip() == '{}':
        command = f'Clear-Content -Path "{file_path}"'
    else:
        command = f'Set-Content -Path "{file_path}" -Value @\"\n{updated_yaml}\"@'

    response = winrm_session.run_ps(command)
    if response.status_code != 0:
        raise Exception(f"Failed to write file: {response.std_err.decode()}")

    return check_config(winrm_session, {k: None for k in keys_to_delete}, file_path, expect_absence=True)


def set_service_status(
    winrm_session: winrm.Session,
    service_name: str,
    action: Literal['start', 'stop', 'restart'] = 'restart',
    timeout: int = 15,
    local_username: str = 'mgmtlocal',  # for slave service
    local_group: str = 'Administrators'  # for slave service
):
    """
    Производит над выбранным сервисом указанное действие. Возвращает строку, если такой службы нет,
    True в случае успеха или исключение при ошибке.
    """
    valid_actions = ['start', 'stop', 'restart']
    if action not in valid_actions:
        raise ValueError(f"Invalid action '{action}'. Valid actions are {valid_actions}.")

    template = 'set_service_status.j2'
    context = {
        'service_name': service_name,
        'action': action,
        'timeout': timeout,
        'user_name': local_username,
        'group_name': local_group
    }
    command = render_template(template, context)

    result = winrm_session.run_ps(command)
    output = result.std_out.decode('utf-8').strip()

    if output == '':
        return True
    elif 'Service' in output and 'not found.' in output:
        return output
    else:
        raise Exception(output)


def convert_reg_path(reg_path: str) -> str:
    """
    Преобразует путь в реестре Windows из формата с "Computer/HKEY_LOCAL_MACHINE" в "HKLM:" и т.д.
    Возвращает преобразованный путь для PowerShell.
    """
    full_path = reg_path.replace("/", "\\").rstrip("\\")

    path_mapping = {
        "Computer\\HKEY_LOCAL_MACHINE": "HKLM:",
        "Computer\\HKEY_CURRENT_USER": "HKCU:",
        "Computer\\HKEY_CLASSES_ROOT": "HKCR:",
        "Computer\\HKEY_USERS": "HKU:",
        "Computer\\HKEY_CURRENT_CONFIG": "HKCC:"
    }
    for key, mapped in path_mapping.items():
        if full_path.startswith(key):
            return full_path.replace(key, mapped, 1)

    return full_path


def check_reg_path(
    winrm_session: winrm.Session,
    reg_suffix: str = '',
    reg_prefix: str = config.get('win', {}).get('registry_prefix', 'HKLM:\\SOFTWARE\\WOW6432Node\\')
) -> bool:
    """
    Проверяет, существует ли указанный путь в реестре Windows.
    Возвращает True, если путь существует, иначе False.
    """
    full_path = convert_reg_path(reg_prefix + reg_suffix)

    command = f"""
        if (Get-Item -Path '{full_path}' -ErrorAction SilentlyContinue) {{
            $true
        }} else {{
            $false
        }}
    """
    response = winrm_session.run_ps(command)
    return str(response.std_out.strip().lower()) in ["true", "b'true'"]


def create_reg_path(
    winrm_session: winrm.Session,
    reg_suffix: str = '',
    reg_prefix: str = config.get('win', {}).get('registry_prefix', 'HKLM:\\SOFTWARE\\WOW6432Node\\')
) -> bool:
    """
    Создает указанный путь в реестре Windows.
    Возвращает True, если путь успешно создан или уже существует, иначе False.
    """
    full_path = convert_reg_path(reg_prefix + reg_suffix)

    command = f"""
        if (-not (Get-Item -Path '{full_path}' -ErrorAction SilentlyContinue)) {{
            New-Item -Path '{full_path}' -Force | Out-Null
        }}
    """
    winrm_session.run_ps(command)
    return check_reg_path(winrm_session, reg_suffix, reg_prefix)


def delete_reg_path(
    winrm_session: winrm.Session,
    reg_suffix: str = '',
    reg_prefix: str = config.get('win', {}).get('registry_prefix', 'HKLM:\\SOFTWARE\\WOW6432Node\\')
) -> bool:
    """
    Удаляет указанный путь в реестре Windows.
    Возвращает True, если путь успешно удалён или не существовал, иначе False.
    """
    full_path = convert_reg_path(reg_prefix + reg_suffix)

    command = f"""
        if (Get-Item -Path '{full_path}' -ErrorAction SilentlyContinue) {{
            Remove-Item -Path '{full_path}' -Recurse -Force | Out-Null
        }}
    """
    winrm_session.run_ps(command)
    return not check_reg_path(winrm_session, reg_suffix, reg_prefix)


def check_reg_prop(
    winrm_session: winrm.Session,
    prop_name: str,
    prop_type: Literal['String', 'Binary', 'DWORD', 'QWORD', 'ExpandString', 'MultiString'],
    prop_value: str | bytearray | bytes | list[str],
    reg_suffix: str = '',
    reg_prefix: str = config.get('win', {}).get('registry_prefix', 'HKLM:\\SOFTWARE\\WOW6432Node\\')
) -> bool:
    """
    Проверяет, существует ли указанное свойство в реестре Windows с заданным типом и значением.
    Для свойств типа Binary в качестве prop_value указывается массив байтов (bytearray([18, 35])) либо эквивалентная байтовая строка (b'\\\\x12\\\\x23').
    Для свойств типов DWORD и QWORD в качестве prop_value указывается значение в десятичной системе счисления.
    Для свойств типа MultiString в качестве prop_value указывается список строковых значений (каждый элемент - отдельная строка).
    Возвращает True, если свойство существует и соответствует указанным типу и значению, иначе False.
    """
    if prop_type == 'Binary':
        prop_value_str = ','.join([str(b) for b in prop_value])
    elif prop_type == 'MultiString':
        prop_value_str = ','.join([f"'{v}'" for v in prop_value])
    else:
        prop_value_str = str(prop_value)

    template = 'check_reg_prop.j2'
    context = {
        'prop_name': prop_name,
        'prop_type': prop_type,
        'prop_value_str': prop_value_str,
        'prop_value_length': len(prop_value),
        'full_path': convert_reg_path(reg_prefix + reg_suffix)
    }

    command = render_template(template, context)
    response = winrm_session.run_ps(command)
    return str(response.std_out.strip().lower()) in ["true", "b'true'"]


def set_reg_prop(
    winrm_session: winrm.Session,
    prop_name: str,
    prop_type: Literal['String', 'Binary', 'DWORD', 'QWORD', 'ExpandString', 'MultiString'],
    prop_value: str | bytearray | bytes | list[str],
    reg_suffix: str = '',
    reg_prefix: str = config.get('win', {}).get('registry_prefix', 'HKLM:\\SOFTWARE\\WOW6432Node\\')
) -> bool:
    """
    Создает или обновляет указанное свойство в реестре Windows с заданным типом и значением.
    Для свойств типа Binary в качестве prop_value указывается массив байтов (bytearray([18, 35])) либо эквивалентная байтовая строка (b'\\\\x12\\\\x23').
    Для свойств типов DWORD и QWORD в качестве prop_value указывается значение в десятичной системе счисления.
    Для свойств типа MultiString в качестве prop_value указывается список строковых значений (каждый элемент - отдельная строка).
    Возвращает True, если свойство успешно создано или обновлено и соответствует указанным типу и значению, иначе False.
    """
    if prop_type == 'Binary':
        prop_value_str = ','.join([str(b) for b in prop_value])
    elif prop_type == 'MultiString':
        prop_value_str = ','.join([f"'{v}'" for v in prop_value])
    else:
        prop_value_str = str(prop_value)

    template = 'set_reg_prop.j2'
    context = {
        'prop_name': prop_name,
        'prop_type': prop_type,
        'prop_value_str': prop_value_str,
        'full_path': convert_reg_path(reg_prefix + reg_suffix)
    }

    command = render_template(template, context)
    response = winrm_session.run_ps(command)
    if response.status_code != 0:
        raise Exception(f"Error setting the '{prop_name}' property: {response.std_err}")

    return check_reg_prop(winrm_session, prop_name, prop_type, prop_value, reg_suffix, reg_prefix)


def delete_reg_prop(
    winrm_session: winrm.Session,
    prop_name: str,
    reg_suffix: str = '',
    reg_prefix: str = config.get('win', {}).get('registry_prefix', 'HKLM:\\SOFTWARE\\WOW6432Node\\')
) -> bool:
    """
    Удаляет указанное свойство из реестра Windows.
    Возвращает True, если свойство успешно удалено или не существует.
    Возвращает False, если свойство всё ещё существует.
    """
    template = 'delete_reg_prop.j2'
    context = {
        'prop_name': prop_name,
        'full_path': convert_reg_path(reg_prefix + reg_suffix)
    }

    command = render_template(template, context)
    response = winrm_session.run_ps(command)
    return str(response.std_out.strip().lower()) in ["true", "b'true'"]


# new_config = {
#     "defender": {
#         "old_mode": "false",
#     },
#     "llmnr": {
#         "interval_seconds": "25",
#     },
#     "auth": {
#         "attempts_count": "3",
#         "attempts-exceed-strategy": {
#             "permanent-lock": "true"
#         }
#     },
#     "password": {
#         "validation": {
#             "policy": "ff5"
#         }
#     }
# }
#
# less_config = [
#     'auth.attempts_count',
#     'defender'
# ]
# print(update_config(get_winrm_connection('172.16.5.119'), new_config, 'C:/Program Files (x86)/Xello/SlaveServer/external123.yml'))
# print(check_config(get_winrm_connection('172.16.5.119'), new_config, 'C:/Program Files (x86)/Xello/SlaveServer/external123.yml'))
# print(delete_config(get_winrm_connection('172.16.5.119'), less_config, 'C:/Program Files (x86)/Xello/SlaveServer/external123.yml'))

# print(set_service_status(get_winrm_connection('172.16.5.119'), 'slave', 'restart', 10))

# print(check_reg_path(get_winrm_connection('172.16.5.119'), 'Xello\\12345'))
# print(create_reg_path(get_winrm_connection('172.16.5.119'), 'Xello\\12345'))
# print(delete_reg_path(get_winrm_connection('172.16.5.119'), 'Xello\\12345'))

# print(check_reg_prop(get_winrm_connection('172.16.5.119'), '1', 'MultiString', ['gagagwag', 'awegwgw', '321'], 'Xello'))
# print(check_reg_prop(get_winrm_connection('172.16.5.119'), '2', 'Binary', bytearray([66, 48]), 'Xello'))
# print(check_reg_prop(get_winrm_connection('172.16.5.119'), '3', 'DWORD', '4676', 'Xello'))
# print(check_reg_prop(get_winrm_connection('172.16.5.119'), '4', 'QWORD', '4124', 'Xello'))
# print(check_reg_prop(get_winrm_connection('172.16.5.119'), '5', 'ExpandString', 'eagawg', 'Xello'))
# print(check_reg_prop(get_winrm_connection('172.16.5.119'), 'installpath', 'String', 'C:\\Users\\o.sorockij\\Downloads\\xello_slave_server_5.6.0.0_1280.exe', 'Xello'))

# print(set_reg_prop(get_winrm_connection('172.16.5.119'), 'test_test1', 'MultiString', ['123', 'abc', '321'], 'Xello'))
# print(set_reg_prop(get_winrm_connection('172.16.5.119'), 'test_test2', 'String', 'agaewgwg', 'Xello'))
# print(set_reg_prop(get_winrm_connection('172.16.5.119'), 'test_test3', 'Binary', b'\x35\x14', 'Xello'))
# print(set_reg_prop(get_winrm_connection('172.16.5.119'), 'test_test4', 'DWORD', '25235', 'Xello'))
# print(set_reg_prop(get_winrm_connection('172.16.5.119'), 'test_test5', 'QWORD', '63663', 'Xello'))
# print(set_reg_prop(get_winrm_connection('172.16.5.119'), 'test_test6', 'ExpandString', 'ara awega awagat', 'Xello'))

# print(delete_reg_prop(get_winrm_connection('172.16.5.119'), 'test_test1', 'Xello'))
# print(delete_reg_prop(get_winrm_connection('172.16.5.119'), 'test_test2', 'Xello'))
# print(delete_reg_prop(get_winrm_connection('172.16.5.119'), 'test_test3', 'Xello'))
# print(delete_reg_prop(get_winrm_connection('172.16.5.119'), 'test_test4', 'Xello'))
# print(delete_reg_prop(get_winrm_connection('172.16.5.119'), 'test_test5', 'Xello'))
# print(delete_reg_prop(get_winrm_connection('172.16.5.119'), 'test_test6', 'Xello'))
