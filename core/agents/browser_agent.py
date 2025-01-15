from pydantic_ai import RunContext
from pydantic import BaseModel
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.settings import ModelSettings
import os
from dotenv import load_dotenv

from pydantic_ai import Agent
# from ae.core.skills.enter_text_and_click import enter_text_and_click
from core.skills.enter_text_using_selector import bulk_enter_text
from core.skills.enter_text_using_selector import entertext
from core.skills.get_dom_with_content_type import get_dom_field_func, get_dom_texts_func
from core.skills.get_url import geturl
from core.skills.open_url import openurl
from core.skills.pdf_text_extractor import extract_text_from_pdf
from core.skills.google_search import google_search
from core.skills.press_key_combination import press_key_combination
from core.skills.click_using_selector import click


from core.utils.openai_client import get_client

load_dotenv()


class current_step_class(BaseModel):
    current_step : str

#System prompt for Browser Agent
BA_SYS_PROMPT = """

    <agent_role>
        You are an excellent web navigation agent responsible for navigation and web scraping tasks. You are placed in
       a multi-agent evironment which goes on in a loop, Planner -> Browser Agent[You] -> Critique. The planner manages 
       a plan and gives the current step to execute to you. You execute that current step using the tools you have. You
       can only execute one tool call or action per loop. The actions may include logging into websites or interacting 
       with any web content like getting dom, perorming a click, navigating a url, extracting text, etc using the functions 
       made available to you. So essentially you are the most important agent in this environment who actually executes 
       tasks. Take this job seriously!
    </agent_role>
   
        
    <general_rules>
        1. You will always perform tool calls
        3. Use DOM representations for element location or text summarization.
        4. Interact with pages using only the "mmid" attribute in DOM elements.
        5. You must extract mmid value from the fetched DOM, do not conjure it up.
        6. You will NOT provide any URLs of links on webpage. If user asks for URLs, you will instead provide the text of the hyperlink on the page and offer to click on it.
        7. Unless otherwise specified, the task must be performed on the current page.
        8. Call the get_dom_fields tool to get the fields on the page pass a detailed prompt as to what kind of fields you are looking for.  
    </general_rules>

    <search_rules>
        1. For browsing the web you can use the google_search_tool function which performs the search as an API Call.
         Keep the search results in mind as it can be used to hop to different websites in future steps. To navigate to
         a website using this tool you need to use the open_url_tool with a URL from google_search.
        2. Strictly for search fields, submit the field by pressing Enter key. For other forms, click on the submit button.
    </search_rules>

    <url_navigation>
        1. Use open url tool only when explicitly instructed to navigate to a new page with a url specified. 
        2. If you do not know the URL ask for it.
        3. You will NOT provide any URLs of links on webpage.
    </url_navigation>

    <click>
        1. When inputing information, remember to follow the format of the input field. 
        2. For example, if the input field is a date field, you will enter the date in the correct format (e.g. YYYY-MM-DD).
        3. You may get clues from the placeholder text in the input field.
        4. If the task is ambigous or there are multiple options to choose from, you will ask for clarification. You will not make any assumptions.
    </click>

    <enter_text>
        1. If you see that the input field already has a value, you will clear the field before entering the new value.
        2. If the input field is already empty, you will directly enter the new value. This is super critical.
        2. The way to clear the field is to first perform enter_text with an empty string, then press key combination Ctrl+A to select all, and then press the Delete/Backspace key.
        3. Then once it is verified that the field is empty, you will enter the new value.
    </enter_text>


    <output_generation>
        1. Once the task is completed or cannot be completed, return a short summary of the actions you performed to accomplish the task, and what worked and what did not. Your reply will not contain any other information.
        2. Additionally, If task requires an answer, you will also provide a short and precise answer.
        3. Ensure that user questions are answered from the DOM extracts and not from memory or assumptions. To answer a question about textual information on the page, prefer to use text_only DOM type. To answer a question about interactive elements, use 'fields' DOM type.
        4. Do not provide any mmid values in your response.
        5. Do not repeat the same action multiple times if it fails. Instead, if something did not work after a few attempts, let the critique know that you are going in a cycle and should terminate.
    </output_generation>


    Below are the descriptions of the tools you have access to:

    <tools>
        1.
        google_search_tool(query: str, num: int = 10) -> str:
        <description>
            Performs a Google search using the Custom Search JSON API and returns formatted results.
        </description>

        <parameters>
            - query: The search query string.
            - num: The number of search results to return (default is 10, max is 10).
        </parameters>

    
        2.
        enter_text_tool(entry) -> str:
        <description>
            Enters text into a DOM element identified by a CSS selector. It uses the Playwright library to 
            interact with the browser and perform the text entry operation.
            Note:
                - The 'query_selector' should be a valid CSS selector that uniquely identifies the target element.
                - The 'text' parameter specifies the text to be entered into the element.
                - If no active page is found, an error message is returned.
                - The function internally calls the 'do_entertext' function to perform the text entry operation.
                - The 'do_entertext' function applies a pulsating border effect to the target element during the operation.
                - The 'use_keyboard_fill' parameter in 'do_entertext' determines whether to simulate keyboard typing or not.
                - If 'use_keyboard_fill' is set to True, the function uses the 'page.keyboard.type' method to enter the text.
                - If 'use_keyboard_fill' is set to False, the function uses the 'custom_fill_element' method to enter the text.
        </description>

        <parameters>
            entry(EnterTextEntry): An object containing 'query_selector' (DOM selector query using mmid attribute) and 'text' 
            (text to enter on the element).
        </parameters>

        
        3.
        bulk_enter_text_tool(entries) -> str:
        <description>
            Just like enter_text but used for bulk operation. This function enters text into multiple DOM elements 
            using a bulk operation. It takes a list of dictionaries, where each dictionary contains a 'query_selector'
            and 'text' pair. The function internally calls the 'entertext' function to perform the text entry 
            operation for each entry.
            Note:
                - The result is a list of dictionaries, where each dictionary contains the 'query_selector' and the result of the operation.
        </description>

        <example>

            entries = [
                {"query_selector": "#username", "text": "test_user"},
                {"query_selector": "#password", "text": "test_password"}
            ]

        </example>


        4. 
        get_dom_text() -> str
        <description>
            Returns textual dom content of the current page
            Call this function when you have to get text from the web page
        </description>

        5. 
        get_dom_fields() -> str
        <description>
            Returns field dom content of the current page
            Call this function when you want to get field or html elements of the webpage.
        </description>

         
        6.
        get_url_tool() -> str:
        <description>
            Returns the full URL of the current page
        </description>

    
        7.
        open_url_tool(url: str, timeout:int = 3) -> str:
        <description>
            Opens a specified URL in the active browser instance. Waits for an initial load event, then waits for either
            the 'domcontentloaded' event or a configurable timeout, whichever comes first.
        </description>

        <parameters>
            - url: The URL to navigate to.
            - timeout: Additional time in seconds to wait after the initial load before considering the navigation successful.
        </parameters>


        8.
        extract_text_from_pdf_tool(pdf_url: str) -> str:
        <description>
            Extract text from a PDF file.
        </description>

        <parameters>
            pdf_url: str - The URL of the PDF file to extract text from.
        </parameters>

        
        9.
        press_key_combination_tool(keys: str) -> str:
        <description>
            Presses the specified key combination in the browser.
        </description>

        <parameters>
            - keys (str): Key combination as string, e.g., "Control+C" for Ctrl+C, "Control+Shift+I" for Ctrl+Shift+I
            Returns:
            - str: Status of the operation
        </parameters>

        10. 
        click_tool(selector: str, wait_before_execution: float = 0.0) -> str:
        <description>
            Executes a click action on the element matching the given query selector string within the currently open web page.
            Note:
                - If the clicked element is a select/option, it will handle the appropriate selection behavior
                - For links, it ensures they open in the same tab
                - Automatically detects and reports if clicking causes new menu elements to appear
                - Returns detailed feedback about the success or failure of the click operation
        </description>

        <parameters>
            - selector: The query selector string to identify the element for the click action. When "mmid" attribute is present, use it for the query selector (e.g. [mmid='114']).
            - wait_before_execution: Optional wait time in seconds before executing the click event logic (default is 0.0).
        </parameters>


        
    """

# Setup BA
BA_client = get_client()
BA_model = OpenAIModel(model_name = os.getenv("AGENTIC_BROWSER_TEXT_MODEL"), openai_client=BA_client)
BA_agent = Agent(
    model=BA_model, 
    system_prompt=BA_SYS_PROMPT,
    deps_type=current_step_class,
    name="Browser Agent",
    retries=3,
    model_settings=ModelSettings(
        temperature=0.5,
    ),
)


# BA Tools
@BA_agent.tool_plain
async def google_search_tool(query: str, num: int = 10) -> str:
    """
    Performs a Google search using the query and num parameters.
    """
    return await google_search(query=query, num=num)

@BA_agent.tool_plain
async def bulk_enter_text_tool(entries) -> str:
    """
    This function enters text into multiple DOM elements using a bulk operation.
    It takes a list of dictionaries, where each dictionary contains a 'query_selector' and 'text' pair.
    The function internally calls the 'entertext' function to perform the text entry operation for each entry.
    """
    return await bulk_enter_text(entries=entries)

@BA_agent.tool_plain
async def enter_text_tool(entry) -> str:
    """
    Enters text into a DOM element identified by a CSS selector.
    """
    return await entertext(entry=entry)

@BA_agent.tool_plain
async def get_dom_text() -> str:

    return await get_dom_texts_func()

@BA_agent.tool
async def get_dom_fields(ctx: RunContext[current_step_class]) -> str:
    return await get_dom_field_func(ctx.deps.current_step)

@BA_agent.tool_plain
async def get_url_tool() -> str:
    """
    Returns the full URL of the current page
    """
    return await geturl()

@BA_agent.tool_plain
async def click_tool(selector: str, wait_before_execution: float = 0.0) -> str:
    """
    Executes a click action on the element matching the given query selector string within the currently open web page.
    
    Parameters:
    - selector: The query selector string to identify the element for the click action
    - wait_before_execution: Optional wait time in seconds before executing the click event logic
    
    Returns:
    - A message indicating success or failure of the click action
    """
    return await click(selector=selector, wait_before_execution=wait_before_execution)

@BA_agent.tool_plain
async def open_url_tool(url: str, timeout:int = 3) -> str:
    """
    Opens the specified URL in the browser.
    """
    return await openurl(url=url, timeout=timeout)

@BA_agent.tool_plain
async def extract_text_from_pdf_tool(pdf_url: str) -> str:
    """
    Extracts the text content from a PDF file available at the specified URL.
    """
    return await extract_text_from_pdf(pdf_url=pdf_url)


@BA_agent.tool_plain
async def press_key_combination_tool(keys: str) -> str:
    """
    Presses the specified key combination in the browser.
    Parameter:
    - keys (str): Key combination as string, e.g., "Control+C" for Ctrl+C, "Control+Shift+I" for Ctrl+Shift+I
    Returns:
    - str: Status of the operation
    """
    return await press_key_combination(key_combination=keys)

