"""Utilities for Chainlit query caching + rendering."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

import chainlit as cl

from src.logging import setup_logging

logger = setup_logging("cache_utils")

RunAgentFn = Callable[..., Any]


def _extract_tool_calls_list(result: Any) -> list[str]:
    tool_calls: list[str] = []
    for msg in result.all_messages():
        for p in getattr(msg, "parts", []):
            if getattr(p, "part_kind", "") == "tool-call" and hasattr(p, "tool_name"):
                tool_calls.append(p.tool_name)
    return tool_calls


def _extract_tool_lines_from_result(result: Any) -> list[str]:
    TOOL_AGENTS = {
        "validate_against_personal_info": "validator",
        "review_draft": "reviewer",
    }
    tool_info: dict[Any, dict[str, Any]] = {}
    for msg in result.all_messages():
        for p in getattr(msg, "parts", []):
            part_kind = getattr(p, "part_kind", "")
            if part_kind == "tool-call" and hasattr(p, "tool_name"):
                args_str = ""
                args = getattr(p, "args", None)
                if args:
                    if isinstance(args, dict):
                        key_args: list[str] = []
                        for k, v in args.items():
                            if isinstance(v, str):
                                key_args.append(f"{k}={v[:30]}..." if len(v) > 30 else f"{k}={v}")
                            elif isinstance(v, list):
                                key_args.append(f"{k}=[{len(v)} items]")
                            else:
                                key_args.append(f"{k}={v}")
                        args_str = ", ".join(key_args)
                    elif isinstance(args, str):
                        args_str = f"... ({len(args)} chars)"
                tid = getattr(p, "tool_call_id", id(p))
                tool_info[tid] = {"name": p.tool_name, "args": args_str, "result": None}
            elif part_kind == "tool-return" and hasattr(p, "content"):
                tid = getattr(p, "tool_call_id", None)
                if tid and tid in tool_info:
                    content = str(p.content)
                    tool_info[tid]["result"] = (
                        content[:200] + "..." if len(content) > 200 else content
                    )

    lines: list[str] = []
    for info in tool_info.values():
        agent = TOOL_AGENTS.get(info["name"], "")
        agent_label = f" → **{agent} agent**" if agent else ""
        line = f"🔧 **{info['name']}**({info['args']}){agent_label}"
        if info.get("result"):
            r = str(info["result"])
            line += f"\n   ↳ {r[:150] + '...' if len(r) > 150 else r}"
        lines.append(line)
    return lines


def _strip_think(raw_output: str, *, show_reasoning: bool) -> tuple[str, str | None]:
    think_match = re.search(r"<think>(.*?)</think>", raw_output, re.DOTALL)
    if show_reasoning and think_match:
        reasoning = think_match.group(1).strip()
        reply = re.sub(r"<think>.*?</think>", "", raw_output, flags=re.DOTALL).strip()
        return reply, reasoning
    return raw_output, None


def serialize_messages(messages: Any) -> list:
    serialized: list[dict[str, Any]] = []
    for msg in messages:
        msg_data: dict[str, Any] = {"role": getattr(msg, "role", None), "parts": []}
        for p in getattr(msg, "parts", []):
            part_data: dict[str, Any] = {"part_kind": getattr(p, "part_kind", None)}
            if hasattr(p, "tool_name"):
                part_data["tool_name"] = p.tool_name
            if hasattr(p, "tool_call_id"):
                part_data["tool_call_id"] = p.tool_call_id
            if hasattr(p, "args"):
                part_data["args"] = p.args
            if hasattr(p, "content"):
                part_data["content"] = str(p.content)
            msg_data["parts"].append(part_data)
        serialized.append(msg_data)
    return serialized


def format_tool_info_from_cache(traces_json: str | None) -> list[str]:
    if not traces_json:
        return []
    try:
        messages = json.loads(traces_json)
        TOOL_AGENTS = {
            "validate_against_personal_info": "validator",
            "review_draft": "reviewer",
        }
        tool_info: dict[Any, dict[str, Any]] = {}
        for msg in messages:
            for p in msg.get("parts", []):
                if p.get("part_kind") == "tool-call" and "tool_name" in p:
                    args_str = ""
                    args = p.get("args")
                    if args:
                        if isinstance(args, dict):
                            key_args: list[str] = []
                            for k, v in args.items():
                                if isinstance(v, str):
                                    key_args.append(
                                        f"{k}={v[:30]}..." if len(v) > 30 else f"{k}={v}"
                                    )
                                elif isinstance(v, list):
                                    key_args.append(f"{k}=[{len(v)} items]")
                                else:
                                    key_args.append(f"{k}={v}")
                            args_str = ", ".join(key_args)
                        elif isinstance(args, str):
                            args_str = f"... ({len(args)} chars)"
                    tid = p.get("tool_call_id", id(p))
                    tool_info[tid] = {"name": p["tool_name"], "args": args_str, "result": None}
                elif p.get("part_kind") == "tool-return" and "content" in p:
                    tid = p.get("tool_call_id")
                    if tid and tid in tool_info:
                        content = str(p["content"])
                        tool_info[tid]["result"] = (
                            content[:200] + "..." if len(content) > 200 else content
                        )

        step_parts: list[str] = []
        for info in tool_info.values():
            agent = TOOL_AGENTS.get(info["name"], "")
            agent_label = f" → **{agent} agent**" if agent else ""
            line = f"🔧 **{info['name']}**({info['args']}){agent_label}"
            if info["result"]:
                r = str(info["result"])
                line += f"\n   ↳ {r[:150] + '...' if len(r) > 150 else r}"
            step_parts.append(line)
        return step_parts
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning("Failed to parse cached traces: %s", e)
        return []


async def render_chat_with_cache(
    *,
    assistant: Any,
    user_message: str,
    run_agent: RunAgentFn,
    show_reasoning: bool,
) -> str:
    cached = assistant.get_cached_query(user_message)
    if cached is not None:
        raw_output = cached["final_output"]
        reply, reasoning = _strip_think(raw_output, show_reasoning=show_reasoning)
        step_parts = ["📦 **Cached Result**"]
        if reasoning:
            step_parts.append(reasoning)
        step_parts.extend(format_tool_info_from_cache(cached.get("traces_json")))
        async with cl.Step(name="🤔 Thinking...", type="llm") as step:
            step.output = "\n\n".join(step_parts) if step_parts else "📦 **Cached Result**"
        return reply

    prompt, deps = assistant.prepare_turn(user_message)
    async with cl.Step(name="🤔 Thinking...", type="llm") as step:
        result = await run_agent(assistant.main, prompt, deps=deps, label="main")
        raw_output = result.output or ""

        tool_calls_list = _extract_tool_calls_list(result)
        if tool_calls_list:
            logger.info(
                "chainlit main_agent_complete tool_calls=%d tools=%s output_len=%d",
                len(tool_calls_list),
                ", ".join(tool_calls_list),
                len(raw_output),
            )
        else:
            logger.warning(
                "chainlit main_agent_complete no_tool_calls output_len=%d",
                len(raw_output),
            )

        reply, reasoning = _strip_think(raw_output, show_reasoning=show_reasoning)
        step_parts: list[str] = []
        if reasoning:
            step_parts.append(reasoning)
        step_parts.extend(_extract_tool_lines_from_result(result))
        if step_parts:
            step.output = "\n\n".join(step_parts)
        else:
            usage = result.usage()
            step.output = f"📝 Direct answer ({usage.output_tokens} tokens)"

        traces = serialize_messages(result.all_messages())
        usage = result.usage()
        logs = {
            "tool_calls": tool_calls_list,
            "usage": {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
            },
        }
        assistant.save_query_cache(user_message, raw_output, traces, logs)
        return reply
