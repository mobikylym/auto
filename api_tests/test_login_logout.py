import allure
from api_tests.common import base


@allure.feature('API Tests')
@allure.story('Authorization')
@allure.title('Login and logout')
def test_login_logout():
    with allure.step('Авторизация'):
        session = base.get_session()

    with allure.step('Отправка GET запроса с использованием сессии'):
        response = session.get('management/policies')
        assert response.status_code == 200, f"Ожидали 200, получили {response.status_code}"

    with allure.step('Разлогин'):
        response = session.post('management/auth/logout')
        assert response.status_code == 204, f'Ожидали 204, получили {response.status_code}'

        response = session.get('management/policies')
        assert response.status_code == 401, f'Ожидали 401, получили {response.status_code}'
