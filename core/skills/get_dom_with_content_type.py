import os
import time
from typing import Annotated
from typing import Any

from playwright.async_api import Page

from core.browser_manager import PlaywrightManager
from core.utils.dom_helper import wait_for_non_loading_dom_state
from core.utils.get_detailed_accessibility_tree import do_get_accessibility_info
from core.utils.logger import logger
from core.utils.ui_messagetype import MessageType
import logfire
from config import SOURCE_LOG_FOLDER_PATH

async def get_dom_texts_func() -> Annotated[str | None, "The text content of the DOM"]:
    """
    Retrieves the text content of the active page's DOM.

    Parameters
    ----------
    current_step : str
        The current step in the workflow being executed. This helps track and log the context 
        of the DOM extraction operation.

    Returns
    -------
    str | None
        The text content of the page including image alt texts.

    Raises
    ------
    ValueError
        If no active page is found.
    """
    logger.info("Executing Get DOM Text Command")
    logfire.info("Executing Get DOM Text Command")
    
    start_time = time.time()

    # Create and use the PlaywrightManager
    browser_manager = PlaywrightManager(browser_type='chromium', headless=False)
    page = await browser_manager.get_current_page()
    if page is None:
        raise ValueError('No active page found. OpenURL command opens a new page.')

    await wait_for_non_loading_dom_state(page, 2000)
    
    # Get filtered text content including alt text from images
    text_content = await get_filtered_text_content(page)
    file_path = os.path.join(SOURCE_LOG_FOLDER_PATH, 'text_only_dom.txt')
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(text_content)

    elapsed_time = time.time() - start_time
    logger.info(f"Get DOM Text Command executed in {elapsed_time:.2f} seconds")
    
    
    return text_content


async def get_dom_field_func(
    current_step: Annotated[str, "The current step in the workflow being executed"],
) -> Annotated[dict[str, Any] | None, "The interactive fields data from the DOM"]:
    """
    Retrieves all interactive fields from the active page's DOM.
    """
    logger.info("Executing Get DOM Fields Command")
    logfire.info("Executing Get DOM Fields Command")
    
    start_time = time.time()
    print(f"Current step: {current_step}")

    browser_manager = PlaywrightManager(browser_type='chromium', headless=False)
    page = await browser_manager.get_current_page()
    if page is None:
        raise ValueError('No active page found. OpenURL command opens a new page.')

    await wait_for_non_loading_dom_state(page, 2000)
    
    # Get all interactive elements, including clickable ones
    raw_data = await do_get_accessibility_info(page, only_input_fields=True)

    elapsed_time = time.time() - start_time
    logger.info(f"Get DOM Fields Command executed in {elapsed_time:.2f} seconds")
    
    print(raw_data)
    return raw_data


async def get_filtered_text_content(page: Page) -> str:
    """Helper function to get filtered text content from the page."""
    text_content = await page.evaluate("""
        () => {
            // Array of query selectors to filter out
            const selectorsToFilter = ['#tawebagent-overlay'];

            // Store the original visibility values to revert later
            const originalStyles = [];

            // Hide the elements matching the query selectors
            selectorsToFilter.forEach(selector => {
                const elements = document.querySelectorAll(selector);
                elements.forEach(element => {
                    originalStyles.push({ element: element, originalStyle: element.style.visibility });
                    element.style.visibility = 'hidden';
                });
            });

            // Get the text content of the page
            let textContent = document?.body?.innerText || document?.documentElement?.innerText || "";

            // Get all the alt text from images on the page
            let altTexts = Array.from(document.querySelectorAll('img')).map(img => img.alt);
            altTexts = "Other Alt Texts in the page: " + altTexts.join(' ');

            // Revert the visibility changes
            originalStyles.forEach(entry => {
                entry.element.style.visibility = entry.originalStyle;
            });
            
            return textContent + " " + altTexts;
        }
    """)
    return text_content


def prompt_constructor(inputs: str) -> str:
    """Helper function to construct a prompt string with system prompt and inputs."""
    return f"Inputs :\n{inputs}"