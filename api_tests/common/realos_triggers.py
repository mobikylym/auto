import base64
import os
import platform
import re
import httpx
import socket
import subprocess
import threading
import time
import mysql.connector
import yaml
from mysql.connector import Error
from ftplib import FTP, error_perm, error_temp
import paramiko
from smb.SMBConnection import SMBConnection
from smb.base import NotReadyError
from smb.smb_structs import OperationFailure


def load_config(config_path='config.yaml'):
    with open(config_path, 'r') as file:
        conf = yaml.safe_load(file)
    return conf


config = load_config()

paramiko.Transport._preferred_keys = ['ssh-rsa', 'ecdsa-sha2-nistp256', 'ecdsa-sha2-nistp384', 'ecdsa-sha2-nistp521']
paramiko.Transport._preferred_kex = ['diffie-hellman-group-exchange-sha256', 'diffie-hellman-group14-sha1']
paramiko.Transport._preferred_ciphers = ['aes128-ctr', 'aes192-ctr', 'aes256-ctr']
paramiko.Transport._preferred_macs = ['hmac-sha2-256', 'hmac-sha1']


def clear_known_hosts(trap_server: str, known_hosts_file: str):
    """Удаляет все записи с данным хостом из файла known_hosts."""
    new_host_keys = []
    if os.path.exists(known_hosts_file):
        with open(known_hosts_file, 'r') as f:
            for line in f:
                if trap_server not in line:
                    new_host_keys.append(line)

    with open(known_hosts_file, 'w') as f:
        f.writelines(new_host_keys)


def db_trigger(
    trap_server: str,
    port: int = 3306,
    database: str = 'default',
    username: str = 'root',
    password: str = 'qwerty'
) -> bool:
    connection = None

    try:
        connection = mysql.connector.connect(
            host=trap_server,
            port=port,
            database=database,
            user=username,
            password=password
        )

        if connection.is_connected():
            return True

    except Error as e:
        if 'Unhandled query: SET NAMES' in str(e):
            return True
        else:
            raise Exception(f'Error connecting to MySQL: {e}')

    finally:
        if connection is not None and connection.is_connected():
            connection.close()


def ftp_trigger(
    trap_server: str,
    username: str = 'root',
    password: str = 'qwerty',
    port: int = 21
) -> bool:
    ftp = FTP()

    try:
        ftp.connect(trap_server, port)
        ftp.login(username, password)
        return True

    except error_perm:
        return False

    finally:
        if ftp.sock:
            try:
                ftp.quit()
            except error_temp:
                pass


def sftp_trigger(
    trap_server: str,
    username: str = 'root',
    password: str = 'qwerty',
    port: int = 22,
    timeout: int = 4
) -> bool:
    known_hosts_file = os.path.expanduser("~/.ssh/known_hosts")
    clear_known_hosts(trap_server, known_hosts_file)

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    def close_connection():
        client.close()

    timer = threading.Timer(timeout, close_connection)
    timer.start()

    try:
        client.connect(
            hostname=trap_server,
            port=port,
            username=username,
            password=password,
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout
        )

        host_key = client.get_transport().get_remote_server_key()

        with open(known_hosts_file, 'a') as f:
            f.write(f"{trap_server} {host_key.get_name()} {host_key.get_base64()}\n")

        sftp = client.open_sftp()
        sftp.close()
        timer.cancel()

        return True

    except (EOFError, paramiko.SSHException) as e:
        if 'EOF during negotiation' in str(e):
            return True
        return False
    finally:
        client.close()


def ssh_trigger(
    trap_server: str,
    username: str = 'root',
    password: str = 'qwerty',
    port: int = 22,
    timeout: int = 4
) -> bool:
    known_hosts_file = os.path.expanduser("~/.ssh/known_hosts")
    clear_known_hosts(trap_server, known_hosts_file)

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(trap_server, port=port, username=username, password=password, timeout=timeout)

        host_key = client.get_transport().get_remote_server_key()
        with open(known_hosts_file, 'a') as f:
            f.write(f"{trap_server} {host_key.get_name()} {host_key.get_base64()}\n")

        if client.get_transport() is None or not client.get_transport().is_active():
            return False
        return True

    except paramiko.SSHException:
        return False
    finally:
        client.close()


def icmp_trigger(trap_server: str) -> bool:
    """
    Делает попытку отправки 4 пакетов на указанный сервер.
    Так как ханипот на все соединения отвечает 'Request timed out.', невозможно точно знать, удачна ли попытка получения инцидента,
    поэтому метод всегда возвращает True.
    Инцидент может приходить с задержкой до 60 секунд.
    """
    output = 'NUL 2>&1' if platform.system().lower() == 'windows' else '/dev/null 2>&1'
    os.system(f'ping {trap_server} > {output}')
    return True


def scan_trigger(
    trap_server: str,
    ports: list = (21, 22, 79, 81, 88, 106, 3306, 5800, 5900, 8080, 8081, 8888, 9100, 9999, 80, 443),
    attempts: int = 3
) -> bool:
    """
    По умолчанию делает 3 запроса доступности на каждый указанный порт сервера.
    Однократной отправки зачатую бывает мало для получения инцидента.
    Всегда возвращает True, кроме случая, когда при попытке отправки возникает исключение.
    Инцидент может приходить с задержкой до 60 секунд.
    """
    for port in ports:
        for attempt in range(attempts):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.connect_ex((trap_server, port))
    return True


def rpc_trigger(trap_server: str) -> bool:
    """
    Делает 3 запроса доступности на порт 135, занятый сервисом RPC.
    Всегда возвращает True, кроме случая, когда при попытке отправки возникает исключение.
    Инцидент может приходить с задержкой до 60 секунд.
    """
    return scan_trigger(trap_server, [135])


def winrm_trigger(
    trap_server: str,
    port: int = 5985
) -> bool:
    """
    Делает 3 запроса доступности на указанный порт, занятый сервисом WinRM.
    Всегда возвращает True, кроме случая, когда при попытке отправки возникает исключение.
    Инцидент может приходить с задержкой до 60 секунд.
    """
    return scan_trigger(trap_server, [port])


def rdp_trigger(trap_server: str) -> bool:
    """
    ВАЖНО! Метод работает исключительно при запуске с Windows, так как задействует утилиту mstsc.
    При первом запуске на каждую ловушку необходимо выдать разрешение на подключение в интерфейсе системы,
    а также ввести креды подключения по умолчанию, чтобы запуск утилиты сразу триггерил RDP.
    """
    proc = subprocess.Popen(["mstsc", "/v:" + trap_server])
    time.sleep(5)
    subprocess.run(["taskkill", "/F", "/PID", str(proc.pid)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return True


def smb_and_win_trigger(
    trap_server: str,
    username: str = 'guest',
    password: str = 'qwerty',
    open_folder: str = None,
    port: int = 445
) -> bool:
    """
    Триггер WIN срабатывает только если попытку авторизоваться предпринимает пользователь guest.\n
    Триггер SMB срабатывает всегда, кроме случая, когда указана open_folder НЕ из списка в интерфейсе МГМТ,
    а пользователь указан НЕ guest, потому что в этом случае не создаётся событие безопасности.\n
    Возвращает True во всех случаях успешной авторизации и запроса open_folder.
    """
    conn = None
    rand_conn = None
    try:
        conn = SMBConnection(username, password, "client_name", trap_server, use_ntlm_v2=True, is_direct_tcp=True)
        conn.connect(trap_server, port)

        if open_folder:
            rand_conn = SMBConnection("random", "random_password", "client_name", trap_server, use_ntlm_v2=True, is_direct_tcp=True)
            rand_conn.connect(trap_server, port)
            rand_conn.listPath(service_name=open_folder, path='/')

        conn.close()
        return True

    except (OperationFailure, NotReadyError):
        if open_folder:
            rand_conn.close()

        conn.close()
        return True


def web_trigger(
    trap_server: str,
    username: str = 'root',
    password: str = 'qwerty',
    resource: str = ''
) -> bool:
    """
    Создаёт 2 WEB-события: в первом можно указать кастомный ресурс через resource, а во втором креды авторизации.\n
    Возвращает True в случае успешной отправки обоих запросов и получении во втором статус-кода 401.
    """
    try:
        url = f"https://{trap_server}/{resource.lstrip('/')}"
        response = httpx.get(url, verify=False)

        match = re.search(r'var turl\s*=\s*[\"\']([^\"\']+)[\"\']', response.text)
        if match:
            login_endpoint = match.group(1)
        else:
            return False

        time.sleep(2)

        new_url = f"https://{trap_server}{login_endpoint}"
        auth_header = f"Basic {base64.b64encode(f'{username}:{password}'.encode()).decode()}"
        new_response = httpx.get(new_url, headers={"Authorization": auth_header}, verify=False)

        return new_response.status_code == 401

    except httpx.RequestError:
        return False


def web_redirect_check(
    trap_server: str,
    is_redirect_active: bool = True
) -> bool:
    """
    Если редирект включен, то проверяются, что пришёл статус-код 302 и ссылка, на которую перенаправляет ловушка.\n
    Если редирект отключен, то проверяется только статус-код 200.\n
    Возвращает True в случае соответствия ожидаемому поведению редиректа.
    """
    url = f"http://{trap_server}/"
    response = httpx.get(url, verify=False, follow_redirects=False)

    if is_redirect_active and response.status_code == 302:
        return response.headers.get("location") == f"https://{trap_server}/"

    return response.status_code == 302 if is_redirect_active else response.status_code == 200


def smb_folders_check(
    trap_server: str,
    folder_list: list,
    username: str = config.get('win', {}).get('username', 'Administrator'),
    password: str = config.get('win', {}).get('password', 'Logaribe2*'),
    port: int = 445
) -> bool:
    """
    Проверяет наличие на сервере всех общих папок из списка folder_list.\n
    Для корректной работы желательно указывать реальные username и password пользователя сервера.\n
    Возвращает True только в случае, если все папки из списка присутствуют на сервере, либо False при ошибках
    получения списка общих папок с сервера.
    """
    try:
        conn = SMBConnection(username, password, "client_name", trap_server, use_ntlm_v2=True, is_direct_tcp=True)
        conn.connect(trap_server, port)
        shared_folders = [share.name for share in conn.listShares()]

        return all(folder in shared_folders for folder in folder_list)

    except (OperationFailure, NotReadyError):
        return False


# print(db_trigger('172.16.5.121'))
# print(ftp_trigger('172.16.5.121'))
# print(sftp_trigger('172.16.5.121'))
# print(ssh_trigger('172.16.5.121'))
# print(icmp_trigger('172.16.5.121'))
# print(scan_trigger('172.16.5.121'))
# print(rpc_trigger('172.16.5.121'))
# print(winrm_trigger('172.16.5.121'))
# print(rdp_trigger('172.16.5.121'))
# print(smb_and_win_trigger('172.16.5.121'))
# print(web_trigger('172.16.5.121'))
# print(web_redirect_check('172.16.5.121'))
# print(smb_folders_check('172.16.5.121', ['passports']))



# from concurrent.futures import ThreadPoolExecutor
# from itertools import cycle
#
# methods_with_params = [
#     (db_trigger, {'trap_server': '172.16.5.121'}),
#     (ftp_trigger, {'trap_server': '172.16.5.121'}),
#     (sftp_trigger, {'trap_server': '172.16.5.121'}),
#     (ssh_trigger, {'trap_server': '172.16.5.121'}),
#     (icmp_trigger, {'trap_server': '172.16.5.121'}),
#     (scan_trigger, {'trap_server': '172.16.5.121'}),
#     (rpc_trigger, {'trap_server': '172.16.5.121'}),
#     (winrm_trigger, {'trap_server': '172.16.5.121'}),
#     (smb_and_win_trigger, {'trap_server': '172.16.5.121'}),
#     (web_trigger, {'trap_server': '172.16.5.121'})
#     (rdp_trigger, {'trap_server': '172.16.5.90'})
# ]
#
#
# def run_infinite_methods(max_threads=10):
#     with ThreadPoolExecutor(max_workers=max_threads) as executor:
#         method_cycle = cycle(methods_with_params)
#
#         while True:
#             method, params = next(method_cycle)
#             future = executor.submit(lambda m=method, p=params: m(**p))
#             future.add_done_callback(
#                 lambda f, m=method: print(f"{m.__name__} finished with result: {f.result()}")
#             )
#
#             time.sleep(0.01)
#
#
# run_infinite_methods()
