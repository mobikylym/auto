import re
import sys
import time
from typing import Literal
import yaml
import paramiko
from api_tests.common import base


def load_config(config_path='config.yaml'):
    with open(config_path, 'r') as file:
        conf = yaml.safe_load(file)
    return conf


config = load_config()


def execute_with_privileges(
    ssh_session: paramiko.SSHClient,
    command: str,
    root_password: str = config.get('linux', {}).get('root_password', 'xello_root')
):
    """
    Выполняет команду с правами sudo, а если не удается из-за отсутствия привилегий,
    выполняет команду от имени root. Возвращает stdin, stdout и stderr.
    """
    sudo_command = f"echo '{root_password}' | sudo -S {command}"
    stdin, stdout, stderr = ssh_session.exec_command(sudo_command)
    error = stderr.read().decode()

    if "is not in the sudoers file" in error or "permission denied" in error:
        root_command = f"echo '{root_password}' | su -c \"{command}\""
        stdin, stdout, stderr = ssh_session.exec_command(root_command)

    return stdin, stdout, stderr


def read_file_if_exists(
    ssh_session: paramiko.SSHClient,
    file_path: str,
    root_password: str
) -> str:
    """
    Проверяет существование файла и возвращает его содержимое, если он существует.
    В противном случае возвращает пустую строку.
    """
    check_file_command = f"cat {file_path}"
    _, stdout, stderr = execute_with_privileges(ssh_session, check_file_command, root_password)

    file_content = stdout.read().decode().strip()
    error = stderr.read().decode().replace("Password:", "").replace("Пароль:", "").strip()

    if "No such file or directory" in error:
        return ""

    if error:
        raise Exception(f"Failed to read file: {error}")

    return file_content


def get_ssh_connection(
    server: str,
    username: str = config.get('linux', {}).get('username', 'xello'),
    password: str = config.get('linux', {}).get('password', 'xello_root'),
    port: int = 22
) -> paramiko.SSHClient:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(server, port, username, password)

        bash_command = f"""
            command_exists() {{
                command -v "$1" >/dev/null 2>&1
            }}

            if ! command_exists sudo; then
                yes | apt update >/dev/null 2>&1
                yes | apt install -y sudo >/dev/null 2>&1

                if ! command_exists sudo; then
                    echo "Error installing sudo." >&2
                    exit 1
                fi
            fi
        """

        stdin, stdout, stderr = ssh.exec_command(bash_command)
        output = stdout.read().decode('utf-8')

        if 'Error' in output:
            raise Exception(output)

        return ssh

    except Exception as ex:
        print(f'Failed to get SSH connection with server IP "{server}": {ex}')
        sys.exit(1)


def check_config(
    ssh_session: paramiko.SSHClient,
    expected_config: dict,
    file_path: str = config.get('linux', {}).get('config_file_path', '/opt/xello/external.yml'),
    root_password: str = config.get('linux', {}).get('root_password', 'xello_root'),
    expect_absence: bool = False
) -> bool:
    """
    Проверяет наличие или отсутствие всех ключей из expected_config в конфигурационном файле.
    Если expect_absence == True, проверяет, что все ключи отсутствуют (игнорируя значения).
    Если expect_absence == False, проверяет, что все ключи присутствуют с правильными значениями.
    Возвращает True, если условие выполнено, иначе — False.
    """
    file_content = read_file_if_exists(ssh_session, file_path, root_password)
    config_data = yaml.safe_load(file_content) if file_content else {}
    if expect_absence:
        return not base.any_keys_exist(config_data, expected_config)
    else:
        return base.all_keys_match(config_data, expected_config)


def update_config(
    ssh_session: paramiko.SSHClient,
    new_config: dict,
    file_path: str = config.get('linux', {}).get('config_file_path', '/opt/xello/external.yml'),
    root_password: str = config.get('linux', {}).get('root_password', 'xello_root')
) -> bool:
    """
    Обновляет конфигурационный файл, добавляя или изменяя параметры на основе new_config.
    Возвращает True, если все ключи и значения удалось обновить, иначе — False.
    """
    file_content = read_file_if_exists(ssh_session, file_path, root_password)
    config_data = yaml.safe_load(file_content) if file_content else {}
    base.deep_update(config_data, new_config)
    updated_yaml = yaml.dump(config_data)

    write_command = f"sudo bash -c 'cat <<EOF > {file_path}\n{updated_yaml}\nEOF'"
    _, stdout, stderr = execute_with_privileges(ssh_session, write_command, root_password)

    error = stderr.read().decode().replace("Password:", "").replace("Пароль:", "").strip()
    if error:
        raise Exception(f"Failed to write file: {error}")

    return check_config(ssh_session, new_config, file_path, root_password)


def delete_config(
    ssh_session: paramiko.SSHClient,
    keys_to_delete: list[str],
    file_path: str = config.get('linux', {}).get('config_file_path', '/opt/xello/external.yml'),
    root_password: str = config.get('linux', {}).get('root_password', 'xello_root')
) -> bool:
    """
    Удаляет из конфигурационного файла ключи, указанные в keys_to_delete.
    Возвращает True, если все указанные ключи были удалены, иначе — False.
    """
    file_content = read_file_if_exists(ssh_session, file_path, root_password)
    config_data = yaml.safe_load(file_content) if file_content else {}

    for key_path in keys_to_delete:
        base.delete_key(config_data, key_path)

    updated_yaml = yaml.dump(config_data)
    if str(updated_yaml).strip() == '{}':
        write_command = f'sudo truncate -s 0 "{file_path}"'
    else:
        write_command = f"sudo bash -c 'cat <<EOF > {file_path}\n{updated_yaml}\nEOF'"
    _, stdout, stderr = execute_with_privileges(ssh_session, write_command, root_password)

    error = stderr.read().decode().replace("Password:", "").replace("Пароль:", "").strip()
    if error:
        raise Exception(f"Failed to write file: {error}")

    return check_config(ssh_session, {k: None for k in keys_to_delete}, file_path, root_password, expect_absence=True)


def get_service_status(
    ssh_session: paramiko.SSHClient,
    service_name: str
):
    """
    Возвращает строку статуса указанной службы с сервера.
    """
    command = f"systemctl status {service_name}"
    stdin, stdout, stderr = ssh_session.exec_command(command)
    output = stdout.read().decode('utf-8')

    status_line = re.search(r'Active: .+', output)
    if status_line:
        return status_line.group(0).strip()
    else:
        return f"Service '{service_name}' not found."


def set_service_status(
    ssh_session: paramiko.SSHClient,
    service_name: str,
    action: Literal['start', 'stop', 'restart'] = 'restart',
    timeout: int = 5,
    root_password: str = config.get('linux', {}).get('root_password', 'xello_root'),
    close_connection: bool = True
):
    """
    Производит над выбранным сервисом указанное действие. Возвращает строку, если такой службы нет,
    True в случае успеха или исключение при ошибке.
    """
    def execution_part():
        stdin, stdout, stderr = execute_with_privileges(ssh_session, command, root_password)
        error = stderr.read().decode('utf-8').replace("Password:", "").replace("Пароль:", "").strip()
        if error:
            raise RuntimeError(error)
        time.sleep(timeout)
        return get_service_status(ssh_session, service_name)

    valid_actions = ['start', 'stop', 'restart']
    if action not in valid_actions:
        raise ValueError(f"Invalid action '{action}'. Valid actions are {valid_actions}.")

    status_output = get_service_status(ssh_session, service_name)
    if 'not found' in status_output:
        return f"Service '{service_name}' not found."

    is_active = 'Active: active (running)' in status_output

    try:
        command = f"systemctl {action} {service_name}"

        if action == 'start':
            if is_active:
                return True
            else:
                status_output = execution_part()
                if "Active: active (running)" in status_output:
                    return True
                else:
                    raise RuntimeError(f"Failed to start service '{service_name}'.")

        elif action == 'stop':
            if is_active:
                status_output = execution_part()
                if "Active: inactive (dead)" in status_output:
                    return True
                else:
                    raise RuntimeError(f"Failed to stop service '{service_name}'.")
            else:
                return True

        elif action == 'restart':
            status_output_after_su = execution_part()
            if "Active: active (running)" in status_output_after_su and status_output.split("since")[1].split(";")[0].strip() != status_output_after_su.split("since")[1].split(";")[0].strip():
                return True
            else:
                raise RuntimeError(f"Failed to restart service '{service_name}'.")

    except Exception as e:
        raise RuntimeError(f"Exception occurred: {str(e)}")

    if close_connection:
        ssh_session.close()


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
# print(update_config(get_ssh_connection('172.16.5.120'), new_config))
# print(set_service_status(get_ssh_connection('172.16.5.120'), 'mgmt', 'restart'))
