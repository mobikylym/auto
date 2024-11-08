import pytest
from playwright.sync_api import sync_playwright
from api_tests.common import base


# Список фикстур, которые не нужно выполнять
EXCLUDE_FIXTURES = {"pytestconfig", "delete_output_dir", "base_url", "_verify_url"}


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    for item in items:
        item.fixturenames = [f for f in item.fixturenames if f not in EXCLUDE_FIXTURES]


@pytest.fixture(scope='module')
def session():
    """
    Для API-тестов. Возвращает сессию подключения к МГМТ по умолчанию (из файла конфигурации).
    """
    return base.get_session()


@pytest.fixture(scope='session', params=["chromium", "firefox"])  # chromium firefox webkit
def browser(request):
    with sync_playwright() as p:
        browser = getattr(p, request.param).launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture()
def context(browser):
    """
    Использовать в тест-кейсах, где требуется более 1-й вкладки браузера.
    """
    context = browser.new_context(ignore_https_errors=True)
    yield context
    context.close()


@pytest.fixture()
def page(browser):
    """
    Использовать в тест-кейсах, где достаточно 1-й вкладки браузера.
    """
    cont = browser.new_context(ignore_https_errors=True)
    page = cont.new_page()
    yield page
    cont.close()
