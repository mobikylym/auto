import allure
from ui_tests.common import base


@allure.feature('Login Tests')
@allure.story('User Login')
@allure.title('Test Login')
def test_login(page):
    url = 'https://172.16.5.120/'
    username = 'admin123'
    password = 'admin'

    with allure.step('Открываем страницу МГМТ'):
        page.goto(url)

    with allure.step('Вводим логин'):
        page.fill("input[class='ant-input ant-input-lg css-18vqv95 ant-input-outlined']", username)

    with allure.step('Вводим пароль'):
        page.fill("input[class='ant-input ant-input-lg css-18vqv95']", password)

    with allure.step('Жмём "Войти"'):
        page.click("button[type='submit']")

    with allure.step('Проверяем заголовок страницы'):
        try:
            page.wait_for_selector("h1:has-text('Дашборд')", timeout=5000)
        except Exception:
            base.do_screenshot(page, __name__)
            assert page.is_visible("h1:has-text('Дашборд')"), "Dashboard is not visible."

