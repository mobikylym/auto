import allure
from playwright.sync_api import Page


def do_screenshot(
    page: Page,
    filename: str
) -> None:
    page.screenshot(path=f"screenshots/{filename}.png")
    allure.attach.file(f"screenshots/{filename}.png", attachment_type=allure.attachment_type.PNG)
