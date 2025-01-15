import base64
import os
from typing import Dict
from PIL import Image
from core.utils.openai_client import get_ss_client, get_ss_model

class ImageAnalyzer:

    ss_analysis_history = []

    def __init__(self, image1_path: str, image2_path: str, next_step: str):
        self.image1_path = image1_path
        self.image2_path = image2_path
        self.next_step = next_step
        self.client = None

    @classmethod
    def get_formatted_history(cls) -> str:
        """Format the SS analysis history into a numbered string"""
        if not cls.ss_analysis_history:
            return "No previous SS analysis responses."
        
        formatted_history = "Previous SS Analysis Responses:\n"
        for idx, response in enumerate(cls.ss_analysis_history, 1):
            formatted_history += f"{idx}. {response}\n\n"
        return formatted_history

    @classmethod
    def clear_history(cls):
        """Clear the SS analysis history"""
        cls.ss_analysis_history.clear()
    

    def _encode_image_to_base64(self, image_path: str) -> str:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def _validate_images(self):
        for path in [self.image1_path, self.image2_path]:
            if not os.path.exists(path):
                raise FileNotFoundError(f"Image file not found: {path}")
            try:
                Image.open(path)
            except Exception as e:
                raise ValueError(f"Invalid image file {path}: {str(e)}")

    def analyze_images(self) -> Dict[str, str]:
        self._validate_images()
        self.client = get_ss_client()
        model = get_ss_model()

        base64_image1 = self._encode_image_to_base64(self.image1_path)
        base64_image2 = self._encode_image_to_base64(self.image2_path)

        history_str = self.get_formatted_history()

        prompt = f"""
        You are an excellent screenshot analysis agent. Analyze these two webpage screenshots in detail, considering that this was the action that was intended to be performed next: {self.next_step}.

        Previous SS Analysis Responses: {history_str}

        <rules>
        1. You have been provided 2 screenshots, one is the state of the webpage before the action was performed and the other is the state of the webpage after the action was performed.
        2. If the action was successfully performed, you should be able to see the expected changes in the webpage.
        3. We do not need generic description of what you see in the screenshots that has changed, we need the information and inference on whether the action was successfully performed or not.
        4. If the action was successfully performed, then you need to convey that information and along with that information, you also need to provide information on what changes you see in the screenshots that might have resulted from the action.
        5. If the action was not successfully performed, then you need to convey that information and along with that information, you also need to provide information on what changes you see in the screenshots that might have resulted from the action that indicate the tool call was not executed.
        6. You also need to confirm whether the current action caused any previous actions to fail or not satisfy the request. For example : Entering text in the first field and pressing enter can take us to the next field but any failure in the first field that has occured should be reported. 
        7. The Browser Agent will execute an action such an entering fields or clicking buttons and then say that "the action was successfull" but you have to visually confirm whether the text was entered and completed or it has just been entered and we need further action to complete the text entry.


        <special_case>
        1. One special case is that when the action is searching, we are using SERP API so it will be that the webpage does not change at all. In that case, you need to provide information that the screenshot was unchanged. 
        2. So if the action is searching then you need to provide information that the SS was unchanged. The screenshot being unchanges in the case of search is a special case and does not conclude failure of the search action.
        </special_case>   

        <output rules>
        1. You need to explicitly mention whether the action was successfully performed or not.
        2. You need to check in with what we actually wanted and if that was achieved according to the changes in the screenshots.
        3. You also need to specify if any new elements have appeared or any elements have disappeared.
        4. You need to also explictly mention about any elements related to the action or the element of interest in the screenshots.
        5. If the current action caused any previous actions to fail, then you need to explicitly mention that and tell the Critique exactly what fields were affected and in precisely what manner. 
        6. You also need to explicitly confirm and reassure the Critique that if Browser Agent is saying this action was executed successfully, then was it actually executed successfully or not.

        </output rules>

        </rules>

        
        """

        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image1}",
                                    "detail": "high"
                                }
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image2}",
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=2000
            )
            response_content = response.choices[0].message.content
            self.ss_analysis_history.append(response_content) 
            return response_content
        except Exception as e:
            raise Exception(f"Analysis failed: {str(e)}")