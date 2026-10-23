"""
One way to talk to three AI providers (task 2.4, D-140): OpenAI, Anthropic
Claude and Google Gemini, each with tools ("function calling").

The agent speaks in "turns":
  {"role": "user", "text": "..."}
  {"role": "assistant", "text": "...", "calls": [Call, ...], "raw": <the provider's own message>}
  {"role": "tool", "results": [(Call, {...}), ...]}
Each adapter turns them into the provider's format and the answer back into a
Reply. The provider's own assistant message ("raw") is sent back unchanged in
the same run, because some models need their hidden data (for example
Gemini's thought signatures) returned with the tool results.

Requests: fixed provider addresses only, 45-second timeout, no redirects.
Errors never contain the key.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from decimal import Decimal

import requests

TIMEOUT = 45
MAX_OUTPUT_TOKENS = 1500

# Small, cheap models that support tools (checked 22 October 2026). A business can choose another
# model in its AI connection ("Default model").
DEFAULT_MODELS = {"openai": "gpt-5.4-mini", "anthropic": "claude-haiku-5-5", "gemini": "gemini-3.5-flash-lite"}
# US$ per 1 million tokens (input, output), for the cost estimate. Unknown models use the high guess.
PRICES = {
    "gpt-5.4-mini": (Decimal("0.75"), Decimal("4.50")),
    "gpt-6-luna": (Decimal("0.10"), Decimal("0.50")),
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
    "claude-sonnet-5-5": (Decimal("2.00"), Decimal("10.00")),
    "gemini-3.5-flash-lite": (Decimal("0.30"), Decimal("2.50")),
    "gemini-3.8-flash": (Decimal("0.75"), Decimal("3.75")),
}
UNKNOWN_PRICE = (Decimal("5.00"), Decimal("25.00"))  # on purpose high, so the monthly limit is never under-counted
SUPPORTED = tuple(DEFAULT_MODELS)


class AIError(Exception):
    """A problem talking to the AI provider. The message is safe to log and show."""


@dataclass
class Call:
    id: str
    name: str
    args: dict


@dataclass
class Reply:
    text: str = ""
    calls: list[Call] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    raw: object = None


def model_for(provider: str, config: dict) -> str:
    return (config or {}).get("model") or DEFAULT_MODELS[provider]


def chat(provider: str, api_key: str, model: str, system: str, turns: list[dict], tools: list[dict]) -> Reply:
    if provider not in SUPPORTED:
        raise AIError(f"{provider} cannot answer customers yet. Use OpenAI, Claude or Gemini.")
    return {"openai": _openai, "anthropic": _anthropic, "gemini": _gemini}[provider](api_key, model, system, turns, tools)


def _post(url: str, body: dict, headers: dict, label: str) -> dict:
    try:
        response = requests.post(url, json=body, headers={"Content-Type": "application/json", **headers}, timeout=TIMEOUT, allow_redirects=False)
    except requests.Timeout:
        raise AIError(f"{label} did not answer within {TIMEOUT} seconds.") from None
    except requests.RequestException:
        raise AIError(f"Could not reach {label}. Check the internet connection.") from None
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code in (401, 403):
        raise AIError(f"{label} refused the API key. Check it on the Integrations page.")
    if response.status_code == 404:
        raise AIError(f"{label} does not know this model. Check the model name on the Integrations page.")
    if response.status_code == 429:
        raise AIError(f"{label} says: too many requests or no credit left.")
    if not 200 <= response.status_code < 300:
        error = data.get("error") if isinstance(data, dict) else None
        detail = error.get("message", "") if isinstance(error, dict) else ""
        raise AIError(f"{label} answered with error {response.status_code}. {detail}"[:280].strip())
    if not isinstance(data, dict):
        raise AIError(f"{label} sent an answer that could not be read.")
    return data


# ---------------------------------------------------------------------------
# OpenAI (Chat Completions)
# ---------------------------------------------------------------------------
def _openai(key, model, system, turns, tools) -> Reply:
    messages = [{"role": "system", "content": system}]
    for turn in turns:
        if turn["role"] == "user":
            messages.append({"role": "user", "content": turn["text"]})
        elif turn["role"] == "assistant":
            if turn.get("raw") is not None:
                messages.append(turn["raw"])
                continue
            message = {"role": "assistant", "content": turn.get("text") or ""}
            if turn.get("calls"):
                message["tool_calls"] = [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.args)}}
                                         for c in turn["calls"]]
            messages.append(message)
        else:
            for call, result in turn["results"]:
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})
    body = {"model": model, "messages": messages, "max_completion_tokens": MAX_OUTPUT_TOKENS,
            "tools": [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
                      for t in tools]}
    if not tools:  # plain text (the website editor, task 2.9): OpenAI refuses an empty tool list
        body.pop("tools")
    data = _post("https://api.openai.com/v1/chat/completions", body, {"Authorization": f"Bearer {key}"}, "OpenAI")
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise AIError("OpenAI sent an answer that could not be read.") from None
    calls = []
    for item in message.get("tool_calls") or []:
        function = item.get("function") or {}
        try:
            args = json.loads(function.get("arguments") or "{}")
        except ValueError:
            args = {}
        calls.append(Call(str(item.get("id", "")), str(function.get("name", "")), args if isinstance(args, dict) else {}))
    usage = data.get("usage") or {}
    raw = {k: v for k, v in message.items() if k in ("role", "content", "tool_calls")}
    return Reply((message.get("content") or "").strip(), calls, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0), raw)


# ---------------------------------------------------------------------------
# Anthropic Claude (Messages API)
# ---------------------------------------------------------------------------
def _anthropic(key, model, system, turns, tools) -> Reply:
    messages: list[dict] = []

    def add(role, blocks):
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"].extend(blocks)
        else:
            messages.append({"role": role, "content": list(blocks)})

    for turn in turns:
        if turn["role"] == "user":
            add("user", [{"type": "text", "text": turn["text"]}])
        elif turn["role"] == "assistant":
            if turn.get("raw") is not None:
                add("assistant", copy.deepcopy(turn["raw"]))
                continue
            blocks = [{"type": "text", "text": turn["text"]}] if turn.get("text") else []
            blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.args} for c in turn.get("calls") or []]
            add("assistant", blocks)
        else:
            add("user", [{"type": "tool_result", "tool_use_id": c.id, "content": json.dumps(r, ensure_ascii=False)} for c, r in turn["results"]])
    body = {"model": model, "max_tokens": MAX_OUTPUT_TOKENS, "system": system, "messages": messages,
            "tools": [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]}
    if not tools:
        body.pop("tools")
    data = _post("https://api.anthropic.com/v1/messages", body, {"x-api-key": key, "anthropic-version": "2023-06-01"}, "Anthropic Claude")
    content = data.get("content")
    if not isinstance(content, list):
        raise AIError("Anthropic Claude sent an answer that could not be read.")
    texts, calls = [], []
    for block in content:
        if block.get("type") == "text":
            texts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            args = block.get("input")
            calls.append(Call(str(block.get("id", "")), str(block.get("name", "")), args if isinstance(args, dict) else {}))
    usage = data.get("usage") or {}
    return Reply("\n".join(t for t in texts if t).strip(), calls, int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0), content)


# ---------------------------------------------------------------------------
# Google Gemini (generateContent)
# ---------------------------------------------------------------------------
def _gemini_schema(schema):
    """Gemini's schema names types in capitals (OBJECT, STRING...)."""
    if isinstance(schema, dict):
        return {k: (v.upper() if k == "type" and isinstance(v, str) else _gemini_schema(v)) for k, v in schema.items()}
    if isinstance(schema, list):
        return [_gemini_schema(v) for v in schema]
    return schema


def _gemini(key, model, system, turns, tools) -> Reply:
    contents: list[dict] = []

    def add(role, parts):
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"].extend(parts)
        else:
            contents.append({"role": role, "parts": list(parts)})

    for turn in turns:
        if turn["role"] == "user":
            add("user", [{"text": turn["text"]}])
        elif turn["role"] == "assistant":
            if turn.get("raw") is not None:
                add("model", copy.deepcopy(turn["raw"]))
                continue
            parts = [{"text": turn["text"]}] if turn.get("text") else []
            parts += [{"functionCall": {"name": c.name, "args": c.args}} for c in turn.get("calls") or []]
            add("model", parts)
        else:
            add("user", [{"functionResponse": {"name": c.name, "response": {"result": r}}} for c, r in turn["results"]])
    body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
            "tools": [{"functionDeclarations": [{"name": t["name"], "description": t["description"], "parameters": _gemini_schema(t["parameters"])}
                                                for t in tools]}],
            "generationConfig": {"maxOutputTokens": MAX_OUTPUT_TOKENS}}
    if not tools:  # Gemini refuses an empty list of function declarations
        body.pop("tools")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{requests.utils.quote(model, safe='')}:generateContent"
    data = _post(url, body, {"x-goog-api-key": key}, "Google Gemini")
    try:
        parts = data["candidates"][0]["content"].get("parts") or []
    except (KeyError, IndexError, TypeError, AttributeError):
        raise AIError("Google Gemini sent no answer (it may have blocked the message).") from None
    texts, calls = [], []
    for n, part in enumerate(parts):
        if "text" in part and not part.get("thought"):
            texts.append(part["text"])
        elif "functionCall" in part:
            call = part["functionCall"] or {}
            args = call.get("args")
            calls.append(Call(str(call.get("id") or f"call_{n}"), str(call.get("name", "")), args if isinstance(args, dict) else {}))
    usage = data.get("usageMetadata") or {}
    output = int(usage.get("candidatesTokenCount") or 0) + int(usage.get("thoughtsTokenCount") or 0)
    return Reply("".join(texts).strip(), calls, int(usage.get("promptTokenCount") or 0), output, parts)
