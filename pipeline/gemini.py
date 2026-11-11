"""Gemini adapter for the Interpreter interface.

The model's reply is parsed as JSON and handed back untouched. propose() in
pipeline.interpreter validates it, so a bad or hostile reply becomes an escalation.
"""
import json
import os
import threading

from pipeline.interpreter import RuleInterpreter
from pipeline.untrusted import build_prompt

MAX_REPLY = 2000
MAX_CALLS = 200
TIMEOUT_MS = 10_000
MAX_OUTPUT_TOKENS = 1024


class GeminiInterpreter:
    def __init__(self, generate, *, max_calls: int = MAX_CALLS):
        self._generate = generate
        self._max_calls = max_calls
        self._calls = 0
        self._lock = threading.Lock()

    def interpret(self, note: str):
        with self._lock:
            if self._calls >= self._max_calls:
                raise RuntimeError("model call limit reached")
            self._calls += 1
        text = self._generate(build_prompt(note))
        if not isinstance(text, str) or len(text) > MAX_REPLY:
            raise ValueError("unusable model reply")
        return json.loads(text)


def gemini_generate(api_key: str, model: str):
    """Returns generate(prompt) -> str. The client is built on first use."""
    client = None

    def generate(prompt: str) -> str:
        nonlocal client
        from google import genai
        from google.genai import types

        if client is None:
            client = genai.Client(
                api_key=api_key, http_options=types.HttpOptions(timeout=TIMEOUT_MS)
            )
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ),
        )
        return response.text

    return generate


def build_interpreter(env=None):
    env = os.environ if env is None else env
    if env.get("INTERPRETER") == "gemini":
        key, model = env.get("GEMINI_API_KEY"), env.get("GEMINI_MODEL")
        if key and model:
            return GeminiInterpreter(gemini_generate(key, model))
    return RuleInterpreter()
