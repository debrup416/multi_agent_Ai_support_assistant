"""The LLM seam for the Semantic Kernel layer: a LiteLLM-backed chat-completion connector.

Semantic Kernel has no built-in LiteLLM connector, so this is the SK equivalent of the core
``app/llm/litellm_client.py`` and ADK's ``LiteLlm``: every runtime drives the model through
LiteLLM in-process, resolving the model via ``settings.litellm_model_string`` (e.g.
``anthropic/claude-haiku-4-5``) with the key passed explicitly. Provider is auto-detected
from which API key is present (``LLM_PROVIDER`` overrides).

The maintainer-recommended way to add a custom LLM to SK is to subclass
``ChatCompletionClientBase`` (see SK discussion #5654) — the kernel then handles the whole
tool-calling loop. Because LiteLLM speaks the OpenAI request/response shape, we reuse SK's
``OpenAIChatPromptExecutionSettings`` (it already carries ``tools``/``tool_choice``/
``max_tokens``...) and the stock ``update_settings_from_function_call_configuration`` callback,
and only translate the LiteLLM response back into SK content types.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from typing import TYPE_CHECKING, Any, ClassVar

import litellm

from semantic_kernel.connectors.ai.chat_completion_client_base import ChatCompletionClientBase
from semantic_kernel.connectors.ai.function_calling_utils import (
    update_settings_from_function_call_configuration,
)
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceType
from semantic_kernel.connectors.ai.open_ai import OpenAIChatPromptExecutionSettings
from semantic_kernel.contents.annotation_content import AnnotationContent
from semantic_kernel.contents.chat_message_content import ChatMessageContent
from semantic_kernel.contents.file_reference_content import FileReferenceContent
from semantic_kernel.contents.function_call_content import FunctionCallContent
from semantic_kernel.contents.streaming_chat_message_content import StreamingChatMessageContent
from semantic_kernel.contents.streaming_text_content import StreamingTextContent
from semantic_kernel.contents.text_content import TextContent
from semantic_kernel.contents.utils.author_role import AuthorRole
from semantic_kernel.contents.utils.finish_reason import FinishReason
from semantic_kernel.exceptions import ServiceInvalidExecutionSettingsError

from app.config import Settings, get_settings
from app.observability import tracing
from app.observability.logging import get_logger, log_event

if TYPE_CHECKING:
    from semantic_kernel.connectors.ai.function_call_choice_configuration import (
        FunctionCallChoiceConfiguration,
    )
    from semantic_kernel.connectors.ai.prompt_execution_settings import PromptExecutionSettings
    from semantic_kernel.contents.chat_history import ChatHistory

_logger = get_logger("sk.litellm")


class LiteLLMChatCompletion(ChatCompletionClientBase):
    """A Semantic Kernel chat-completion service backed by LiteLLM (any provider).

    ``ai_model_id`` holds the LiteLLM model string (``provider/model``); the API key, request
    timeout, and default max-tokens are resolved once from :class:`~app.config.Settings`.
    """

    MODEL_PROVIDER_NAME: ClassVar[str] = "litellm"
    SUPPORTS_FUNCTION_CALLING: ClassVar[bool] = True

    api_key: str
    request_timeout: float = 30.0
    default_max_tokens: int = 1024

    def __init__(self, settings: Settings | None = None, *, service_id: str = "litellm") -> None:
        s = settings or get_settings()
        # Resolve once at construction so misconfiguration fails fast (mirrors LiteLLMClient).
        super().__init__(
            ai_model_id=s.litellm_model_string,
            service_id=service_id,
            api_key=s.active_api_key.get_secret_value(),
            request_timeout=s.llm_timeout_seconds,
            default_max_tokens=s.llm_max_tokens,
        )

    # region SK overrides

    def get_prompt_execution_settings_class(self) -> type["PromptExecutionSettings"]:
        # LiteLLM is OpenAI-shaped, so the OpenAI settings carry exactly the fields we send.
        return OpenAIChatPromptExecutionSettings

    def service_url(self) -> str | None:
        return None

    def _update_function_choice_settings_callback(
        self,
    ) -> Callable[["FunctionCallChoiceConfiguration", "PromptExecutionSettings", FunctionChoiceType], None]:
        return update_settings_from_function_call_configuration

    def _verify_function_choice_settings(self, settings: "PromptExecutionSettings") -> None:
        if not isinstance(settings, OpenAIChatPromptExecutionSettings):
            raise ServiceInvalidExecutionSettingsError(
                "LiteLLMChatCompletion requires OpenAIChatPromptExecutionSettings."
            )
        if settings.number_of_responses is not None and settings.number_of_responses > 1:
            raise ServiceInvalidExecutionSettingsError(
                "Auto-invocation of tool calls requires number_of_responses == 1."
            )

    def _reset_function_choice_settings(self, settings: "PromptExecutionSettings") -> None:
        if hasattr(settings, "tool_choice"):
            settings.tool_choice = None
        if hasattr(settings, "tools"):
            settings.tools = None

    async def _inner_get_chat_message_contents(
        self, chat_history: "ChatHistory", settings: "PromptExecutionSettings"
    ) -> list["ChatMessageContent"]:
        settings = self._ensure_settings(settings)
        settings.messages = self._prepare_chat_history_for_request(chat_history)
        response = await litellm.acompletion(**self._request_kwargs(settings, stream=False))
        log_event(
            _logger,
            "sk_llm_complete",
            model=self.ai_model_id,
            choices=len(response.choices),
            tools=bool(settings.tools),
        )
        # Record the generation (model/tokens/cost) under the active SK root span.
        usage = getattr(response, "usage", None)
        hidden = getattr(response, "_hidden_params", None)
        tracing.record_generation(
            name="sk",
            model=self.ai_model_id,
            output=(response.choices[0].message.content if response.choices else None),
            prompt_tokens=getattr(usage, "prompt_tokens", None) if usage is not None else None,
            completion_tokens=getattr(usage, "completion_tokens", None) if usage is not None else None,
            total_tokens=getattr(usage, "total_tokens", None) if usage is not None else None,
            cost_usd=hidden.get("response_cost") if isinstance(hidden, dict) else None,
        )
        return [self._chat_message_content(response, choice) for choice in response.choices]

    async def _inner_get_streaming_chat_message_contents(
        self,
        chat_history: "ChatHistory",
        settings: "PromptExecutionSettings",
        function_invoke_attempt: int = 0,
    ) -> AsyncGenerator[list["StreamingChatMessageContent"], Any]:
        settings = self._ensure_settings(settings)
        settings.messages = self._prepare_chat_history_for_request(chat_history)
        response = await litellm.acompletion(**self._request_kwargs(settings, stream=True))
        async for chunk in response:
            if not getattr(chunk, "choices", None):
                continue
            yield [
                self._streaming_chat_message_content(chunk, choice, function_invoke_attempt)
                for choice in chunk.choices
            ]

    def _prepare_chat_history_for_request(
        self, chat_history: "ChatHistory", role_key: str = "role", content_key: str = "content"
    ) -> Any:
        # OpenAI/LiteLLM message dicts; tool calls and tool results serialize via to_dict().
        return [
            message.to_dict(role_key=role_key, content_key=content_key)
            for message in chat_history.messages
            if not isinstance(message, (AnnotationContent, FileReferenceContent))
        ]

    # endregion

    # region helpers

    def _ensure_settings(self, settings: "PromptExecutionSettings") -> OpenAIChatPromptExecutionSettings:
        if isinstance(settings, OpenAIChatPromptExecutionSettings):
            return settings
        return self.get_prompt_execution_settings_from_settings(settings)

    def _request_kwargs(self, settings: OpenAIChatPromptExecutionSettings, *, stream: bool) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.ai_model_id,
            "api_key": self.api_key,
            "timeout": self.request_timeout,
            "messages": settings.messages,
            "max_tokens": settings.max_tokens or self.default_max_tokens,
            "stream": stream,
        }
        if settings.temperature is not None:
            kwargs["temperature"] = settings.temperature
        if settings.tools:
            kwargs["tools"] = settings.tools
            # update_settings_from_function_call_configuration sets tool_choice to a
            # FunctionChoiceType enum; LiteLLM wants its string value ("auto"/"required"/"none").
            choice = settings.tool_choice
            if isinstance(choice, FunctionChoiceType):
                choice = choice.value
            if choice is not None:
                kwargs["tool_choice"] = choice
        return kwargs

    def _chat_message_content(self, response: Any, choice: Any) -> "ChatMessageContent":
        message = choice.message
        items: list[Any] = list(self._tool_calls(getattr(message, "tool_calls", None)))
        if getattr(message, "content", None):
            items.append(TextContent(text=message.content))
        return ChatMessageContent(
            inner_content=response,
            ai_model_id=self.ai_model_id,
            role=self._role(getattr(message, "role", None)),
            items=items,
            finish_reason=self._finish_reason(choice),
        )

    def _streaming_chat_message_content(
        self, chunk: Any, choice: Any, function_invoke_attempt: int
    ) -> StreamingChatMessageContent:
        delta = choice.delta
        items: list[Any] = list(self._tool_calls(getattr(delta, "tool_calls", None)))
        if getattr(delta, "content", None):
            items.append(StreamingTextContent(choice_index=choice.index, text=delta.content))
        return StreamingChatMessageContent(
            choice_index=choice.index,
            inner_content=chunk,
            ai_model_id=self.ai_model_id,
            role=self._role(getattr(delta, "role", None)),
            items=items,
            finish_reason=self._finish_reason(choice),
            function_invoke_attempt=function_invoke_attempt,
        )

    @staticmethod
    def _tool_calls(tool_calls: Any) -> list[FunctionCallContent]:
        if not tool_calls:
            return []
        out: list[FunctionCallContent] = []
        for tool in tool_calls:
            fn = getattr(tool, "function", None)
            if fn is None:
                continue
            out.append(
                FunctionCallContent(
                    id=getattr(tool, "id", None),
                    index=getattr(tool, "index", None),
                    name=getattr(fn, "name", None),
                    arguments=getattr(fn, "arguments", None),
                )
            )
        return out

    @staticmethod
    def _role(role: Any) -> AuthorRole:
        try:
            return AuthorRole(role) if role else AuthorRole.ASSISTANT
        except ValueError:
            return AuthorRole.ASSISTANT

    @staticmethod
    def _finish_reason(choice: Any) -> FinishReason | None:
        raw = getattr(choice, "finish_reason", None)
        if not raw:
            return None
        try:
            return FinishReason(raw)
        except ValueError:
            return None

    # endregion


def build_service(service_id: str = "litellm") -> LiteLLMChatCompletion:
    """The shared LiteLLM-backed chat service for every SK agent.

    Stateless per call, like the core's single ``LiteLLMClient`` — one instance is reused
    across the triage agent and all specialists.
    """
    return LiteLLMChatCompletion(get_settings(), service_id=service_id)
