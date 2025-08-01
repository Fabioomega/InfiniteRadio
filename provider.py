from typing import Optional

class Provider:
    """A provider abstract class with the minium requirements to be a provider"""

    def __init__(self, url: str, api_key: str): ...

    def query_genre(self, system_prompt: str, b64_image: str, model_name: Optional[str]): ...

class OpenAiProvider(Provider):

    def __init__(self, url: str, api_key: str):
        import ssl
        import certifi
        import httpx
        from openai import OpenAI

        try:
            # Create a custom httpx client with proper SSL context
            http_client = httpx.Client(
                verify=False  # Since we're connecting to localhost, we can disable SSL verification
            )

            self.client = OpenAI(
                base_url=url, 
                api_key=api_key,
                http_client=http_client
            )
        except Exception as e:
            # Fallback to basic client if SSL packages not available
            print(f"   WARNING: SSL configuration failed ({e}), using basic client")
            self.client = OpenAI(base_url=url, api_key=api_key)

    def query_genre(self, system_prompt: str, b64_image: str, model_name: Optional[str]):
        response = self.client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{b64_image}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=50,
            temperature=0.0
        )
        
        return response.choices[0].message.content
    

class OllamaProvider(Provider):
    def __init__(self, url: str, api_key: str):
        import ollama
        self.client = ollama.Client(host=url)

    def query_genre(self, system_prompt: str, b64_image: str, model_name: Optional[str]):
        try:
            response = self.client.generate(
                model=model_name,
                prompt='',
                system=system_prompt,
                images=[b64_image],
                options={
                    'temperature': 0.01,
                    'num_predict': 50
                }
            )
            
            return response['response'].strip()
            
        except Exception as e:
            raise RuntimeError(f"Ollama query failed: {e}")