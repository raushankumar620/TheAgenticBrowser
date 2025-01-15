import os
import asyncio
import tiktoken
import logfire
from typing import Optional
from pydantic_ai.result import Usage
from core.agents.browser_agent import BA_agent, BA_SYS_PROMPT, current_step_class
from core.agents.planner_agent import PA_agent, PA_SYS_PROMPT
from core.agents.critique_agent import CA_agent, CA_SYS_PROMPT
from core.browser_manager import PlaywrightManager 
from core.utils.ss_analysis import ImageAnalyzer
from core.utils.openai_client import get_client
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolReturnPart
from core.utils.logger import logger
from core.utils.message_type import MessageType
from core.utils.openai_msg_parser import AgentConversationHandler, ConversationStorage
from core.utils.custom_exceptions import CustomException, PlannerError, BrowserNavigationError, SSAnalysisError, CritiqueError


tokenizer = tiktoken.encoding_for_model("gpt-4o")


def ensure_tool_response_sequence(messages):
    """Ensures that every tool call has a corresponding tool response"""
    tool_calls = {}
    result = []
    
    for msg in messages:
        if isinstance(msg, dict) and 'tool_calls' in msg.get('parts', [{}])[0]:
            # Store tool calls
            for tool_call in msg['parts'][0]['tool_calls']:
                tool_calls[tool_call['tool_call_id']] = False
            result.append(msg)
        elif isinstance(msg, dict) and 'tool_return' in msg.get('parts', [{}])[0]:
            # Mark tool call as responded
            tool_call_id = msg['parts'][0].get('tool_call_id')
            if tool_call_id in tool_calls:
                tool_calls[tool_call_id] = True
            result.append(msg)
        else:
            result.append(msg)
    
    # Check if all tool calls have responses
    missing_responses = [id for id, has_response in tool_calls.items() if not has_response]
    if missing_responses:
        raise ValueError(f"Missing tool responses for: {missing_responses}")
        
    return result



def extract_tool_interactions(messages):
    """
    Extracts tool calls and their corresponding responses from browser agent messages.
    Returns a formatted string of all tool interactions.
    """
    tool_interactions = {}
    
    for msg in messages:
        # Handle tool calls
        if msg.kind == 'response':
            for part in msg.parts:
                if hasattr(part, 'part_kind') and part.part_kind == 'tool-call':
                    tool_interactions[part.tool_call_id] = {
                        'call': {
                            'tool_name': part.tool_name,
                            'args': part.args.args_json
                        },
                        'response': None
                    }
        
        # Handle tool responses
        elif msg.kind == 'request':
            for part in msg.parts:
                if hasattr(part, 'part_kind') and part.part_kind == 'tool-return':
                    if part.tool_call_id in tool_interactions:
                        tool_interactions[part.tool_call_id]['response'] = {
                            'content': part.content
                        }
    
    # Format tool interactions into a string
    interactions_str = ""
    for tool_id, interaction in tool_interactions.items():
        call = interaction['call']
        response = interaction['response']
        interactions_str += f"Tool Call: {call['tool_name']}\n"
        interactions_str += f"Arguments: {call['args']}\n"
        if response:
            interactions_str += f"Response: {response['content']}\n"
        interactions_str += "---\n"
    
    return interactions_str


def prompt_constructor(inputs):
    """Constructs a prompt string with system prompt and inputs"""
    return f"Inputs :\n{inputs}"

def filter_tool_interactions_for_critique(tool_interactions_str: str) -> str:
    """
    Filter the tool interactions string to replace DOM tool responses with placeholder
    and remove any additional DOM content.
    """
    # Split the interactions by the separator
    interactions = tool_interactions_str.split("---\n")
    filtered_interactions = []
    
    for interaction in interactions:
        if not interaction.strip():  # Skip empty interactions
            continue
            
        # Check if this is a DOM-related tool call
        if "Tool Call: get_dom_text" in interaction or "Tool Call: get_dom_fields" in interaction:
            # Split the interaction into lines
            lines = interaction.split('\n')
            # Keep only the essential lines
            filtered_lines = []
            for line in lines:
                if line.startswith("Tool Call:") or line.startswith("Arguments:"):
                    filtered_lines.append(line)
                elif line.startswith("Response:"):
                    # Replace DOM response with placeholder and stop processing more lines
                    filtered_lines.append("Response: DOM successfully fetched")
                    break  # Important: Stop processing any more lines from this interaction
            
            filtered_interactions.append('\n'.join(filtered_lines))
        else:
            # For non-DOM tools, keep the interaction as is
            filtered_interactions.append(interaction)
    
    # Rejoin with the separator
    return "---\n".join(filtered_interactions) + ("---\n" if filtered_interactions else "")


def filter_dom_messages(messages):
    """
    Filter message history to replace all DOM responses with placeholder text.
    """
    DOM_TOOLS = {'get_dom_text', 'get_dom_fields'}
    filtered_messages = []
    
    for msg in messages:
        if isinstance(msg, ModelRequest) and msg.parts:
            part = msg.parts[0]
            if (hasattr(part, 'part_kind') and 
                part.part_kind == 'tool-return' and
                part.tool_name in DOM_TOOLS):
                
                # Create new ToolReturnPart with modified content
                new_part = ToolReturnPart(
                    tool_name=part.tool_name,
                    content="DOM successfully fetched",
                    tool_call_id=part.tool_call_id,
                    timestamp=part.timestamp,
                    part_kind='tool-return'
                )
                # Create new ModelRequest with modified part
                filtered_messages.append(ModelRequest(
                    parts=[new_part],
                    kind='request'
                ))
            else:
                filtered_messages.append(msg)
        else:
            filtered_messages.append(msg)
    
    return filtered_messages


class Orchestrator:
    logfire.configure(send_to_logfire='if-token-present', scrubbing=False)

    def __init__(self, input_mode: str = "GUI_ONLY") -> None:
        self.client = get_client()
        self.browser_manager = None
        self.shutdown_event = asyncio.Event()
        self.input_mode = input_mode
        self.conversation_handler = AgentConversationHandler()
        self.conversation_storage = ConversationStorage()
        self.terminate = False
        self.response_handler = None
        self.message_histories = {
            'planner': [],
            'browser': [],
            'critique': []
        }
        self.cumulative_tokens = {
            'planner': {'total': 0, 'request': 0, 'response': 0},
            'browser': {'total': 0, 'request': 0, 'response': 0}, 
            'critique': {'total': 0, 'request': 0, 'response': 0}
        }
        self.iteration_counter = 0
        self.session_id = None
        self.current_url = None
        self.ss_enabled = os.getenv('AGENTIC_BROWSER_SS_ENABLED', 'false').lower() == 'true'


    def update_token_usage(self, agent_type: str, usage: Usage):
        self.cumulative_tokens[agent_type]['total'] += usage.total_tokens
        self.cumulative_tokens[agent_type]['request'] += usage.request_tokens 
        self.cumulative_tokens[agent_type]['response'] += usage.response_tokens

    def log_token_usage(self, agent_type: str, usage: Usage, step: Optional[int] = None):
        self.update_token_usage(agent_type, usage)
        step_info = f" (Step {step})" if step is not None else ""
        logfire.info(
                f"""
                \nToken Usage for {agent_type}{step_info}:
                \nIteration tokens: {usage.total_tokens}
                \nCumulative tokens: {self.cumulative_tokens[agent_type]['total']}
                \nTotal request tokens: {self.cumulative_tokens[agent_type]['request']}
                \nTotal response tokens: {self.cumulative_tokens[agent_type]['response']}
                """
        )

    async def async_init(self, session_id: Optional[str] = None, start_url: Optional[str] = None):
        """Initialize browser with session support"""
        self.session_id = session_id
        self.current_url = start_url or "google.com"
        
        if not self.browser_manager:
            self.browser_manager = await self.initialize_browser_manager()
            logger.info("Browser initialized for task")
            
            # Navigate to initial URL if provided
            if self.current_url:
                try:
                    await self.browser_manager.navigate_to_url(self.current_url)
                except Exception as e:
                    logger.error(f"Failed to navigate to initial URL: {str(e)}")
                    raise

    async def navigate_to_url(self, url: str):
        """Handle URL navigation"""
        if self.browser_manager:
            # Add URL protocol if missing
            url = "https://" + url if not url.startswith(('http://', 'https://')) else url
            page = await self.browser_manager.get_current_page()
            await page.goto(url)
            self.current_url = url
            logger.info(f"Successfully navigated to: {url}")

    def set_response_handler(self, handler):
        self.response_handler = handler

    async def reset_state(self):
        """Modified reset_state to preserve session data"""
        self.terminate = False
        # Only reset conversation handler if not in a persistent session
        if not self.session_id:
            self.conversation_handler = AgentConversationHandler()
            self.conversation_storage = ConversationStorage()
            self.message_histories = {
                'planner': [],
                'browser': [],
                'critique': []
            }
            ImageAnalyzer.clear_history()
        self.iteration_counter = 0  
    
    async def initialize_browser_manager(self):
        logfire.info("Initializing browser manager")
        if self.input_mode == "API":
            browser_manager = PlaywrightManager(gui_input_mode=False, take_screenshots=True, headless=True)
        else:
            browser_manager = PlaywrightManager(gui_input_mode="GUI_ONLY")
        self.browser_manager = browser_manager
        await self.browser_manager.async_initialize()
        logger.info(f"Browser manager initialized : {browser_manager}")
        return browser_manager
    
    async def notify_client(self, message: str, message_type: MessageType):
        """Send a message to the client-specific notification queue."""
        if self.input_mode == "GUI_ONLY":
            # Skip in GUI mode
            return
        if hasattr(self, "notification_queue") and self.notification_queue:
            self.notification_queue.put({"message": message, "type": message_type.value})
        else:
            logger.warning("No notification queue attached. Skipping client notification.")

    async def run(self, command, start_url: Optional[str] = None):
        if not self.browser_manager:
            self.browser_manager = await self.initialize_browser_manager()

        if start_url and start_url != self.current_url:
            await self.navigate_to_url(start_url)

        try:
            logfire.info(f" Running Loop with User Query: {command}")
            await self.notify_client(f"Executing command: {command}", MessageType.INFO)

            message_history = []

            print(f"Current URL: {self.current_url}")

            if self.browser_manager:
                await self.browser_manager.notify_user(
                    command,
                    message_type=MessageType.USER_QUERY
                )
            
            PA_prompt = (
                f"User Query : {command}"
                "Feedback : None"
                f"Current URL : {self.current_url}"
            )
            
            i = 0
            self.iteration_counter = 0
            while not self.terminate:
                try:
                    self.iteration_counter += 1
                    logfire.debug(f"________Iteration {self.iteration_counter}________") 
                    logfire.info("Running planner agent")
                    logfire.debug(f"\nMessage history : {message_history}\n")

                    # Planner Execution
                    try:
                        validated_history = ensure_tool_response_sequence(self.message_histories['planner'])
                        planner_response = await PA_agent.run(
                            user_prompt=prompt_constructor(PA_prompt),
                            message_history=validated_history
                        )
                        self.conversation_handler.add_planner_message(planner_response)

                        # Update planner's message history
                        self.message_histories['planner'].extend(planner_response.new_messages())
                        
                        
                        plan = planner_response.data.plan
                        c_step = planner_response.data.next_step
                        logfire.info(f"Initial plan : {plan}")
                        logfire.info(f"Current step : {c_step}")
                        await self.notify_client(f"Plan Generated: {plan}", MessageType.INFO)
                        await self.notify_client(f"Current Step: {c_step}", MessageType.INFO)

                        try:
                            if self.iteration_counter == 1:  # Only show plan on first iteration
                                await self.browser_manager.notify_user(
                                    f" {planner_response.data.plan}",
                                    message_type=MessageType.PLAN
                                )
                            await self.browser_manager.notify_user(
                                f"{planner_response.data.next_step}",
                                message_type=MessageType.STEP
                            )
                        except Exception as e:
                            logfire.error(f"Error in notifying plan to the user : {e}")
                            self.notify_client(f"Error in planner: {str(e)}", MessageType.ERROR)
                        
                    except Exception as e:
                        error_str = str(e)
                        if "context_length_exceeded" in error_str or "maximum context length" in error_str:
                            error_msg = "Context length exceeded. The conversation history is too long to continue."
                            logfire.error(error_msg)
                            await self.browser_manager.notify_user(
                                error_msg,
                                message_type=MessageType.ERROR
                            )
                            await self.notify_client(error_msg, MessageType.ERROR)
                            
                            # Create a final response indicating the task couldn't be completed
                            final_response = "Task could not be completed due to conversation length limitations. Please try breaking down your request into smaller steps."
                            
                            if self.response_handler:
                                await self.response_handler(final_response)
                            
                            return final_response

                        raise PlannerError(
                            f"Planner execution failed: {str(e)}",
                            original_error=e
                        )

                    self.log_token_usage(
                        agent_type='planner',
                        usage=planner_response._usage,
                        step=self.iteration_counter
                    )


                    # Pre-Action Screenshot
                    if self.ss_enabled:
                        try:
                            logfire.info("Taking Pre_Action_SS")
                            pre_action_ss = await self.browser_manager.take_screenshots(
                                "Pre_Action_SS", page=None, full_page=False
                            )
                            logfire.info(f"SS Saved to Path: {pre_action_ss}")
                        except Exception as e:
                            error_msg = f"Failed to take Pre_Action_SS: {str(e)}"
                            logfire.error(error_msg, exc_info=True)
                            await self.browser_manager.notify_user(
                                error_msg,
                                message_type=MessageType.ERROR
                            )
                            raise CustomException(error_msg, original_error=e)

                    browser_error = None
                    tool_interactions_str = None

                    # Browser Execution
                    BA_prompt = (
                        f'plan="{plan}" '
                        f'current_step="{c_step}" '
                    )
                    
                    current_step_deps = current_step_class(
                        current_step = c_step
                    )


                    try:
                        logfire.info("Running browser agent")

                        history = filter_dom_messages(self.message_histories['browser'])
                        browser_response = await BA_agent.run(
                            user_prompt=prompt_constructor(BA_prompt),
                            deps=current_step_deps,
                            message_history=history, 
                            # deps=self.browser_manager
                        )
                        self.conversation_handler.add_browser_nav_message(browser_response)

                        # Extract new messages and get tool interactions
                        new_messages = browser_response.new_messages()
                        self.message_histories['browser'].extend(new_messages)
                        tool_interactions_str = extract_tool_interactions(new_messages)

                        # self.message_histories['browser'].extend(browser_response.new_messages())

                        logfire.info(f"All Messages from Browser Agent: {browser_response.all_messages()}")
                        logfire.info(f"Tool Interactions: {tool_interactions_str}")
                        
                        

                        

                        logfire.info(f"Browser Agent Response: {browser_response.data}")
                        # await self.notify_client(f"Current Step Execution: {browser_response.data}", MessageType.INFO)

                        self.log_token_usage(
                            agent_type='browser',
                            usage=browser_response._usage,
                            step=self.iteration_counter
                        )

                    except Exception as e:
                        error_str = str(e)
                        if "context_length_exceeded" in error_str or "maximum context length" in error_str:
                            error_msg = "Context length exceeded. The conversation history is too long to continue."
                            logfire.error(error_msg)
                            await self.browser_manager.notify_user(
                                error_msg,
                                message_type=MessageType.ERROR
                            )
                            await self.notify_client(error_msg, MessageType.ERROR)
                            
                            # Create a final response indicating the task couldn't be completed
                            final_response = "Task could not be completed due to conversation length limitations. Please try breaking down your request into smaller steps."
                            
                            if self.response_handler:
                                await self.response_handler(final_response)
                            
                            return final_response
                        else:
                            # Capture error but don't raise it
                            browser_error = str(e)
                            browser_result = f"Error occurred: {browser_error}"
                            tool_interactions_str = "Error occurred during tool execution"
                            
                            # Log the error
                            logfire.error(f"Browser agent execution error: {browser_error}")
                            await self.browser_manager.notify_user(
                                f"Error in browser execution: {browser_error}",
                                message_type=MessageType.ERROR
                            )


                    # Post_Action_SS Screenshot
                    if self.ss_enabled:
                        try:
                            logfire.info("Taking Post_Action_SS")
                            post_action_ss = await self.browser_manager.take_screenshots(
                                "Post_Action_SS", page=None, full_page=False
                            )
                            logfire.info(f"Post_Action_SS Saved to Path: {post_action_ss}")
                        except Exception as e:
                            error_msg = f"Failed to take Post_Action_SS: {str(e)}"
                            logfire.error(error_msg, exc_info=True)
                            await self.browser_manager.notify_user(
                                error_msg,
                                message_type=MessageType.ERROR
                            )
                            raise CustomException(error_msg, original_error=e)

                        # SS Analysis
                        try:
                            logfire.info("Running SS analysis")
                            
                            
                            ss_analysis_response = ImageAnalyzer(
                                pre_action_ss, 
                                post_action_ss, 
                                c_step
                            ).analyze_images()
                            self.conversation_handler.add_ss_analysis_message(ss_analysis_response)
                            
                            logfire.info(f"SS Analysis Response: {ss_analysis_response}")
                        except Exception as e:
                            error_msg = f"SS Analysis failed: {str(e)}"
                            logfire.error(error_msg, exc_info=True)
                            await self.browser_manager.notify_user(
                                error_msg,
                                message_type=MessageType.ERROR
                            )
                            await self.notify_client(f"Error in SS Analysis: {str(e)}", MessageType.ERROR)
                            raise SSAnalysisError(error_msg, original_error=e)


                    # Critique Agent
                    try:
                        logfire.info("Running critique agent")
                        filtered_interactions = filter_tool_interactions_for_critique(tool_interactions_str)
                        logfire.debug(f"Original tool interactions: {tool_interactions_str}")
                        logfire.debug(f"Filtered tool interactions: {filtered_interactions}")
    
                        CA_prompt = (
                            f'plan="{plan}" '
                            f'next_step="{c_step}" '
                            f'tool_response="{browser_response.data}" '
                            f'tool_interactions="{filtered_interactions}" '
                            f'ss_analysis="{ss_analysis_response if self.ss_enabled else "SS analysis not available"}"'
                            f'browser_error="{browser_error if browser_error else "None"}"'
                        )

                        critique_response = await CA_agent.run(
                            user_prompt=prompt_constructor(CA_prompt),
                            message_history=self.message_histories['critique']
                        )
                        self.conversation_handler.add_critique_message(critique_response)

                        # Update critique's message history
                        self.message_histories['critique'].extend(critique_response.new_messages())

                        
                        logfire.info(f"Critique Feedback: {critique_response.data.feedback}")
                        logfire.info(f"Critique Response: {critique_response.data.final_response}")
                        logfire.info(f"Critique Terminate: {critique_response.data.terminate}")
                        await self.notify_client(f"Task did not complete, Retrying with Feedback : {critique_response.data.feedback}", MessageType.INFO)

                        self.log_token_usage(
                            agent_type='critique',
                            usage=critique_response._usage,
                            step=self.iteration_counter
                        )

                    except Exception as e:
                        error_str = str(e)
                        if "context_length_exceeded" in error_str or "maximum context length" in error_str:
                            error_msg = "Context length exceeded. The conversation history is too long to continue."
                            logfire.error(error_msg)
                            await self.browser_manager.notify_user(
                                error_msg,
                                message_type=MessageType.ERROR
                            )
                            await self.notify_client(error_msg, MessageType.ERROR)
                            
                            # Create a final response indicating the task couldn't be completed
                            final_response = "Task could not be completed due to conversation length limitations. Please try breaking down your request into smaller steps."
                            
                            if self.response_handler:
                                await self.response_handler(final_response)
                            
                            return final_response
                        
                        raise 

                    openai_messages = self.conversation_handler.get_conversation_history()
                    saved_path = self.conversation_storage.save_conversation(openai_messages, prefix="task")
                    logfire.info(f"Conversation appended to: {saved_path}")

                    # Termination Check
                    if critique_response.data.terminate:
                        await self.browser_manager.notify_user(
                            f"{critique_response.data.final_response}",
                            message_type=MessageType.ANSWER,
                        )
                        final_response = critique_response.data.final_response
                        await self.notify_client(f"Final Response : {final_response}", MessageType.FINAL)

                        if self.response_handler:
                            await self.response_handler(final_response)
                        self.terminate = True
                        return final_response
                    else:
                        PA_prompt = (
                            f"User Query : {command}"
                            f"Previous Plan : {plan}"
                            f"Feedback : {critique_response.data.feedback}"
                        )
                    
                    # Loop Exit

                except Exception as step_error:
                    error_msg = f"Error in execution step {i}: {str(step_error)}"
                    await self.notify_client(f"Error in execution step {i} : {str(step_error)}", MessageType.ERROR)
                    logfire.error(error_msg, exc_info=True)
                    await self.browser_manager.notify_user(
                        error_msg,
                        message_type=MessageType.ERROR
                    )
                    # Optionally retry or continue to next iteration
                    continue

        except Exception as e:
            error_msg = f"Critical Error in orchestrator: {str(e)}"
            await self.notify_client(f"Error in Orchestrator : {str(e)}", MessageType.ERROR)

            logfire.error(error_msg, exc_info=True)
            await self.browser_manager.notify_user(
                error_msg,
                message_type=MessageType.ERROR
            )
            raise

        finally:
            logfire.info("Orchestrator Execution Completed")
            await self.cleanup()

    async def start(self):
    
        logfire.info("Starting the orchestrator")

        await self.initialize_browser_manager() 

        if self.input_mode == "GUI_ONLY":
            browser_context = await self.browser_manager.get_browser_context()
            await browser_context.expose_function('process_task', self.receive_command) # type: ignore


        await self.wait_for_exit()

    async def receive_command(self, command: str):
        """Process commands with state reset"""
        logger.info(f"Received command from the UI: {command}")
        await self.reset_state()  # Reset state before new command
        
        await self.run(command)


    async def wait_for_exit(self):
        await self.shutdown_event.wait()

    async def shutdown(self):
        if self.browser_manager:
            await self.browser_manager.stop_playwright()

    async def cleanup(self):
        """Modified cleanup to handle session persistence"""
        if self.input_mode != "GUI_ONLY" and not self.session_id:
            # Full cleanup only if not in a persistent session
            if self.browser_manager:
                await self.browser_manager.stop_playwright()
            self.shutdown_event.set()
        else:
            # Partial cleanup for GUI mode or persistent sessions
            await self.reset_state()
            logger.info("Partial cleanup completed - browser preserved for session")

