from __future__ import annotations

import re
from urllib.parse import urljoin

from playwright.sync_api import Page, expect


def url(app_url: str, path: str) -> str:
    return urljoin(app_url.rstrip("/") + "/", path.lstrip("/"))


def login(page: Page, app_url: str, username: str, password: str) -> None:
    page.goto(url(app_url, "/login"))
    page.get_by_label("Username").fill(username)
    page.get_by_label("Password").fill(password)
    page.get_by_role("button", name="Sign in").click()
    expect(page).to_have_url(re.compile(r".*/estimates(?:\?.*)?$"))


def logout(page: Page) -> None:
    page.get_by_role("button", name="Sign out").click()
    expect(page).to_have_url(re.compile(r".*/login$"))


def create_estimate(page: Page, app_url: str, product: str) -> int:
    page.goto(url(app_url, "/estimates/new"))
    label = "Create MEP Estimate" if product == "MEP" else "Create CIP Estimate"
    page.get_by_role("button", name=label).click()
    expect(page).to_have_url(re.compile(r".*/estimate/\d+$"))
    return int(page.url.rstrip("/").rsplit("/", 1)[-1])


def wait_for_autosave(page: Page, rid: int, action) -> None:
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and re.search(rf"/estimate/{rid}(?:\?.*)?$", response.url) is not None
    ) as pending:
        action()
    response = pending.value
    if response.status >= 400:
        raise AssertionError(f"Autosave failed with HTTP {response.status}: {response.url}")


def fill_and_blur(page: Page, rid: int, locator, value: str) -> None:
    def _change():
        locator.fill(value)
        locator.press("Tab")
    wait_for_autosave(page, rid, _change)


def select_and_save(page: Page, rid: int, locator, value: str) -> None:
    wait_for_autosave(page, rid, lambda: locator.select_option(value=value))


def row_by_text(page: Page, text: str):
    return page.locator("tr").filter(has_text=text).first
