"""
AI CLI Assistant (open / free providers, zero extra dependencies)
--------------------------------------------------------------------
Optional, opt-in helper for the Batch CLI tab: translates a plain-English
request into device CLI commands, and explains console output.

Works with any OpenAI-compatible chat-completions endpoint. Built-in presets:

  - OpenCode Zen   https://opencode.ai/zen/v1      free models (big-pickle...)
  - OpenRouter     https://openrouter.ai/api/v1    many free/open models
  - Groq           https://api.groq.com/openai/v1  free tier, very fast
  - Ollama         http://localhost:11434/v1       fully local, no key needed
  - Custom         any OpenAI-compatible base URL

You supply your own API key per provider (stored locally via QSettings,
never bundled or transmitted anywhere except to the provider you call).
Nothing here ever executes commands on a device directly — generated
commands are only ever handed back as text for review before running.
"""

import requests
from PyQt6.QtCore import QSettings

SETTINGS_ORG = "EveNGLabAutomation"
SETTINGS_APP = "AiAssistantSettings"

# (internal_key, label, default_base_url, default_model, needs_api_key)
PROVIDERS = [
    ("opencode", "OpenCode Zen (free models)",
     "https://opencode.ai/zen/v1", "big-pickle", True),
    ("openrouter", "OpenRouter (free & open models)",
     "https://openrouter.ai/api/v1", "meta-llama/llama-3.3-70b-instruct:free", True),
    ("groq", "Groq (free tier)",
     "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", True),
    ("ollama", "Ollama (local, no key)",
     "http://localhost:11434/v1", "llama3.2", False),
    ("custom", "Custom OpenAI-compatible...",
     "", "", True),
]

DEFAULTS = {p[0]: {"base_url": p[2], "model": p[3], "needs_key": p[4]} for p in PROVIDERS}
PROVIDER_LABELS = {p[0]: p[1] for p in PROVIDERS}

CLI_SYSTEM_PROMPT = (
    "You are a network engineering assistant embedded in a lab automation tool. "
    "The user will describe what they want a network device to do in plain English. "
    "Respond with ONLY the CLI commands to accomplish it, one command per line, in the "
    "exact order they should be run, starting with 'enable' and 'configure terminal' if "
    "configuration mode is needed, and ending with 'end' and 'write memory' if changes were made. "
    "Do not include markdown code fences, explanations, comments, or any text other than the "
    "commands themselves - the output is inserted directly into a command box that will be sent "
    "to a real device console. If the request is ambiguous, make the most common-sense assumption "
    "and proceed rather than asking a clarifying question."
)

EXPLAIN_SYSTEM_PROMPT = (
    "You are a network engineering assistant embedded in a lab automation tool. The user will "
    "paste console output from a network device (which may include command output, errors, or "
    "both). Give a concise, plain-English explanation: what happened, whether there were any "
    "errors and what likely caused them, and a suggested next step if something looks wrong. "
    "Keep it to a short paragraph or a few bullet points - this is displayed in a small panel, "
    "not a report."
)


# ---------------- settings helpers ----------------
def get_selected_provider() -> str:
    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    return settings.value("provider", PROVIDERS[0][0], type=str)


def set_selected_provider(provider: str):
    QSettings(SETTINGS_ORG, SETTINGS_APP).setValue("provider", provider)


def get_api_key(provider: str) -> str:
    return QSettings(SETTINGS_ORG, SETTINGS_APP).value(f"api_key_{provider}", "", type=str)


def set_api_key(provider: str, key: str):
    QSettings(SETTINGS_ORG, SETTINGS_APP).setValue(f"api_key_{provider}", key.strip())


def get_base_url(provider: str) -> str:
    default = DEFAULTS.get(provider, {}).get("base_url", "")
    return QSettings(SETTINGS_ORG, SETTINGS_APP).value(f"base_url_{provider}", default, type=str)


def set_base_url(provider: str, url: str):
    QSettings(SETTINGS_ORG, SETTINGS_APP).setValue(f"base_url_{provider}", url.strip())


def get_model(provider: str) -> str:
    default = DEFAULTS.get(provider, {}).get("model", "")
    return QSettings(SETTINGS_ORG, SETTINGS_APP).value(f"model_{provider}", default, type=str)


def set_model(provider: str, model: str):
    QSettings(SETTINGS_ORG, SETTINGS_APP).setValue(f"model_{provider}", model.strip())


def needs_api_key(provider: str) -> bool:
    return DEFAULTS.get(provider, {}).get("needs_key", True)


def is_configured(provider: str = None) -> bool:
    provider = provider or get_selected_provider()
    base = get_base_url(provider).strip()
    model = get_model(provider).strip()
    key_ok = bool(get_api_key(provider).strip()) or not needs_api_key(provider)
    return bool(base) and bool(model) and key_ok


class AiAssistant:
    """Thin client for any OpenAI-compatible chat-completions endpoint."""

    def __init__(self, provider: str = None):
        self.provider = provider or get_selected_provider()
        if self.provider not in DEFAULTS:
            raise RuntimeError(f"Unknown AI provider: {self.provider}")

        self.base_url = get_base_url(self.provider).strip().rstrip("/")
        self.model = get_model(self.provider).strip()
        self.api_key = get_api_key(self.provider).strip()

        if not self.base_url:
            raise RuntimeError("No Base URL configured for this provider.")
        if not self.model:
            raise RuntimeError("No Model configured for this provider.")
        if needs_api_key(self.provider) and not self.api_key:
            raise RuntimeError(
                f"No API key set for {PROVIDER_LABELS[self.provider]}. Paste your key in the "
                f"AI Assistant panel first."
            )

    # ---------------- public API ----------------
    def generate_cli_commands(self, request: str, device_context: str = "Cisco IOS",
                              timeout: float = 45.0) -> str:
        """Translates a plain-English request into device CLI commands (text only)."""
        if not request.strip():
            raise RuntimeError("Enter a description of what you want to configure first.")
        user_content = f"Device platform: {device_context}\n\nRequest: {request.strip()}"
        return self._chat(CLI_SYSTEM_PROMPT, user_content, timeout)

    def explain_output(self, console_output: str, timeout: float = 45.0) -> str:
        """Explains/summarizes console output, focusing on errors if present."""
        if not console_output.strip():
            raise RuntimeError("No console output to explain yet - run some commands first.")
        return self._chat(EXPLAIN_SYSTEM_PROMPT, console_output.strip()[:8000], timeout)

    # ---------------- internals ----------------
    def _chat(self, system_prompt: str, user_content: str, timeout: float) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
            "max_tokens": 1024,
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        except requests.exceptions.Timeout:
            raise RuntimeError(
                f"{url} did not answer within {int(timeout)}s.\n"
                f"- For Ollama: is 'ollama serve' running?\n"
                f"- Otherwise check the Base URL and your connection."
            )
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(f"Couldn't reach {url} ({e.__class__.__name__}). Check the Base URL.")

        if resp.status_code == 401:
            raise RuntimeError("Rejected (401): API key missing, wrong, or expired.")
        if resp.status_code == 404:
            raise RuntimeError(
                f"Not found (404) at {url}. The Base URL usually must end with /v1 "
                f"(e.g. https://api.groq.com/openai/v1)."
            )
        if resp.status_code == 429:
            raise RuntimeError("Rate limited (429): slow down or switch model/provider.")
        if resp.status_code != 200:
            snippet = resp.text[:200]
            raise RuntimeError(f"HTTP {resp.status_code} from provider: {snippet}")

        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError):
            raise RuntimeError(f"Unexpected response shape from provider: {resp.text[:200]}")

        cleaned = self._strip_code_fences((content or "").strip())
        if not cleaned:
            raise RuntimeError("The model returned an empty response. Try rephrasing or another model.")
        return cleaned

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Some open models wrap answers in ```...``` despite instructions -
        strip fences so the result drops cleanly into the command box."""
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        while lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
