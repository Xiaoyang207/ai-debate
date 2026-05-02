"""
辩论引擎核心逻辑。

该模块包含 `DebateEngine` 类,负责管理整个辩论生命周期:
- 创建 AutoGen 团队
- 流式处理消息
- 过滤、立场检测
- 通过回调队列向外部(如 UI)发布事件

引擎设计为与 UI 完全解耦,可独立测试。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_ext.models.openai import OpenAIChatCompletionClient

from models import DebateConfig, STAGE_DEFS
from text_filters import (
    clean_meta_description,
    is_invalid_short_content,
    check_side_drift,
)

logger = logging.getLogger("debate_engine")

DEFAULT_TIMEOUT: float = 600.0
MAX_RETRIES: int = 5
MAX_ITERATIONS_MULTIPLIER: int = 3
STREAM_CLOSE_TIMEOUT: float = 2.0


@dataclass
class DebateEngine:
    config: DebateConfig
    event_callback: Callable[[Dict[str, Any]], None] = lambda msg: None
    _cancel_event: Optional[asyncio.Event] = field(default=None, init=False)
    _pause_event: Optional[asyncio.Event] = field(default=None, init=False)
    _resume_event: Optional[asyncio.Event] = field(default=None, init=False)
    _runner_thread: Optional[threading.Thread] = field(default=None, init=False)

    # -------------------------------------------------------------------------
    # 线程安全的控制接口
    # -------------------------------------------------------------------------

    def cancel(self) -> None:
        if self._runner_thread and self._runner_thread.is_alive():
            loop = self._runner_thread._loop          # type: ignore[attr-defined]
            loop.call_soon_threadsafe(self._cancel_event.set)
            loop.call_soon_threadsafe(self._pause_event.set)
            loop.call_soon_threadsafe(self._resume_event.set)

    def pause(self) -> None:
        if self._runner_thread and self._runner_thread.is_alive():
            loop = self._runner_thread._loop
            loop.call_soon_threadsafe(self._pause_event.set)
            loop.call_soon_threadsafe(self._resume_event.clear)

    def resume(self) -> None:
        if self._runner_thread and self._runner_thread.is_alive():
            loop = self._runner_thread._loop
            loop.call_soon_threadsafe(self._pause_event.clear)
            loop.call_soon_threadsafe(self._resume_event.set)

    def is_running(self) -> bool:
        return (
            self._runner_thread is not None
            and self._runner_thread.is_alive()
            and not self._cancel_event.is_set()
        )

    def join(self, timeout: Optional[float] = None) -> None:
        if self._runner_thread is not None:
            self._runner_thread.join(timeout)

    # -------------------------------------------------------------------------
    # 启动
    # -------------------------------------------------------------------------

    def start(self) -> None:
        if self._runner_thread and self._runner_thread.is_alive():
            raise RuntimeError("辩论引擎已在运行中")
        self._runner_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._runner_thread.start()

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._runner_thread._loop = loop           # 供控制接口使用

        # 创建 asyncio.Event (不再传入 loop 参数)
        self._cancel_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._resume_event = asyncio.Event()

        try:
            loop.run_until_complete(self._debate())
        except Exception as exc:
            logger.exception("辩论引擎未捕获异常")
            self._emit_event({"type": "error", "content": str(exc)})
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            finally:
                loop.close()

    # -------------------------------------------------------------------------
    # 主协程
    # -------------------------------------------------------------------------

    async def _debate(self) -> None:
        config = self.config
        self._emit_event({
            "type": "topic",
            "content": config.topic,
            "stages": config.stages,
        })

        model_client = await self._init_model_client()

        try:
            active_stages = [
                stage_def
                for stage_def in STAGE_DEFS
                if config.stages.get(stage_def["key"], 0) > 0
            ]
            for stage_def in active_stages:
                if self._cancel_event.is_set():
                    break
                await self._run_stage(stage_def, model_client)
                if not self._cancel_event.is_set():
                    await asyncio.sleep(0.1)
        finally:
            try:
                await model_client.close()
            except AttributeError:
                logger.debug("模型客户端未提供 close() 方法,跳过显式关闭")

        if not self._cancel_event.is_set():
            self._emit_event({"type": "end"})

    async def _init_model_client(self) -> OpenAIChatCompletionClient:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return OpenAIChatCompletionClient(
                    model=self.config.model,
                    api_key=self.config.api_key,
                    base_url=self.config.base_url,
                    model_info={
                        "vision": False,
                        "function_calling": True,
                        "json_output": True,
                        "structured_output": False,
                        "family": "deepseek",
                    },
                )
            except Exception as e:
                logger.warning(f"模型客户端初始化失败 (attempt {attempt})")
                if attempt == MAX_RETRIES:
                    raise ConnectionError("模型客户端初始化失败") from e
                await asyncio.sleep(min(2 ** attempt, 8))

    # -------------------------------------------------------------------------
    # 单阶段执行（与原代码一致，未改动核心逻辑）
    # -------------------------------------------------------------------------

    async def _run_stage(
        self,
        stage_def: Dict[str, str],
        model_client: OpenAIChatCompletionClient,
    ) -> None:
        config = self.config
        stage_key = stage_def["key"]
        max_rounds = config.stages.get(stage_key, 0)
        stage_name = stage_def["name"]
        self._emit_event({
            "type": "stage",
            "stage_key": stage_key,
            "stage_name": stage_name,
        })

        pro_agent = self._create_agent(
            name=f"ProSpeaker_{stage_key}",
            speaker=stage_def["pro_speaker"],
            side="正方",
            is_pro=True,
            duty=stage_def["pro_duty"],
            model_client=model_client,
        )
        con_agent = self._create_agent(
            name=f"ConSpeaker_{stage_key}",
            speaker=stage_def["con_speaker"],
            side="反方",
            is_pro=False,
            duty=stage_def["con_duty"],
            model_client=model_client,
        )

        participants = [pro_agent, con_agent] if config.pro_first else [con_agent, pro_agent]
        max_messages = max_rounds * 2 + 10
        team = RoundRobinGroupChat(
            participants=participants,
            termination_condition=MaxMessageTermination(max_messages),
        )

        debate_task = (
            f"辩题:{config.topic}\n"
            "正方立场:完全支持,必须证明正方观点正确。\n"
            "反方立场:完全反对,必须证明正方观点错误。\n"
            "双方必须坚持各自立场,绝不妥协,绝不退让。现在开始辩论。"
        )

        stream = team.run_stream(task=debate_task)
        try:
            await self._process_stream(stream, stage_def, pro_agent, con_agent, max_rounds)
        finally:
            try:
                await asyncio.wait_for(stream.aclose(), timeout=STREAM_CLOSE_TIMEOUT)
            except (asyncio.TimeoutError, Exception):
                logger.debug(f"阶段 {stage_key} 流关闭超时,强制继续")
            del pro_agent, con_agent

    def _create_agent(
        self,
        name: str,
        speaker: str,
        side: str,
        is_pro: bool,
        duty: str,
        model_client: OpenAIChatCompletionClient,
    ) -> AssistantAgent:
        system_msg = self._build_system_prompt(speaker, side, is_pro, duty)
        return AssistantAgent(name=name, model_client=model_client, system_message=system_msg)

    def _build_system_prompt(
        self,
        speaker: str,
        side: str,
        is_pro: bool,
        duty: str,
    ) -> str:
        if is_pro:
            stance = (
                '你必须坚决支持正方观点,绝对不可退让、妥协或承认反方观点的合理性。\n'
                '禁止使用“反方说得也有道理”、“部分同意反方”、“我承认反方有一定道理”等表述。\n'
                '辩论是零和博弈,不存在双赢或中间立场。'
            )
        else:
            stance = (
                '你必须坚决反对正方观点,绝对不可认同、赞同或部分接纳正方观点。\n'
                '禁止使用“确实”、“我承认正方有一定道理”、“双方都有理”、“正方也有正确之处”等表述。\n'
                '辩论是零和博弈,你必须从反方角度质疑和反驳一切正方论据。'
            )
        return (
            f'你是专业的辩论赛{speaker},请用中文进行辩论。\n\n'
            f'当前辩题:{self.config.topic}\n'
            f'你的立场:{side}\n'
            f'你的职责:{duty}\n\n'
            f'【核心立场 - 绝对不可违反】:\n{stance}\n\n'
            f'【重要规则】:\n'
            f'- 每次发言必须控制在{self.config.word_limit}字以内\n'
            f'- 直接输出辩论内容,禁止说“现在进入XX环节”、“我宣布”、“接下来由我发言”等元描述性语言\n'
            f'- 禁止输出“TERMINATE”、“发言完毕”、“以上是我的发言”等结束语\n'
            f'- 用事实、数据和逻辑支撑论点,保持攻击性但不失礼貌\n'
        )

    # -------------------------------------------------------------------------
    # 处理消息流（使用 asyncio.Event 等待，不再阻塞事件循环）
    # -------------------------------------------------------------------------

    async def _process_stream(
        self,
        stream: Any,
        stage_def: Dict[str, str],
        pro_agent: AssistantAgent,
        con_agent: AssistantAgent,
        max_rounds: int,
    ) -> None:
        pro_name = pro_agent.name
        con_name = con_agent.name
        pro_speaker = stage_def["pro_speaker"]
        con_speaker = stage_def["con_speaker"]
        stage_key = stage_def["key"]
        pro_count = con_count = 0
        message_count = 0
        max_iterations = max_rounds * 2 * MAX_ITERATIONS_MULTIPLIER

        debate_task_text = (
            f"辩题:{self.config.topic}\n"
            "正方立场:完全支持,必须证明正方观点正确。\n"
            "反方立场:完全反对,必须证明正方观点错误。\n"
            "双方必须坚持各自立场,绝不妥协,绝不退让。现在开始辩论。"
        )

        async def consume() -> None:
            nonlocal pro_count, con_count, message_count
            async for message in stream:
                while self._pause_event.is_set():
                    await self._resume_event.wait()
                if self._cancel_event.is_set():
                    return

                message_count += 1
                if message_count > max_iterations:
                    self._emit_event({"type": "warning", "content": "达到最大迭代次数,强制结束"})
                    return

                if not (hasattr(message, "content") and message.content and isinstance(message.content, str)):
                    continue

                raw = message.content.strip()
                if raw == "" or raw == debate_task_text:
                    continue
                if len(raw) < 10 or is_invalid_short_content(raw):
                    continue

                content = clean_meta_description(raw)
                if len(content) < 10:
                    continue

                source = message.source
                if source == pro_name:
                    side, speaker, role = "正方", pro_speaker, "ProSpeaker"
                elif source == con_name:
                    side, speaker, role = "反方", con_speaker, "ConSpeaker"
                else:
                    continue

                is_drift, drift_side = check_side_drift(content, side)
                if is_drift:
                    self._emit_event({
                        "type": "warning",
                        "content": f"检测到{drift_side}立场漂移,已过滤该消息",
                    })
                    continue

                if self.config.max_tokens > 0 and len(content) > self.config.max_tokens:
                    content = content[:self.config.max_tokens] + "…"

                if source == pro_name and pro_count < max_rounds:
                    pro_count += 1
                    self._emit_event({
                        "type": "message",
                        "role": role,
                        "content": content,
                        "speaker_name": speaker,
                        "round": pro_count,
                        "total_rounds": max_rounds,
                        "stage_key": stage_key,
                    })
                    await asyncio.sleep(self.config.sleep_between_messages)
                elif source == con_name and con_count < max_rounds:
                    con_count += 1
                    self._emit_event({
                        "type": "message",
                        "role": role,
                        "content": content,
                        "speaker_name": speaker,
                        "round": con_count,
                        "total_rounds": max_rounds,
                        "stage_key": stage_key,
                    })
                    await asyncio.sleep(self.config.sleep_between_messages)

                if pro_count >= max_rounds and con_count >= max_rounds:
                    return

        try:
            await asyncio.wait_for(consume(), timeout=DEFAULT_TIMEOUT)
        except asyncio.TimeoutError:
            self._emit_event({
                "type": "warning",
                "content": f"{stage_def['name']} 超时,强制结束",
            })

    def _emit_event(self, event: Dict[str, Any]) -> None:
        try:
            self.event_callback(event)
        except Exception:
            logger.exception("事件回调异常")