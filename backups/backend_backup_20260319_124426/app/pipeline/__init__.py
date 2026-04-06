"""Pipeline package — pluggable, channel-based processor architecture.

Key exports for convenience:
  Message, Channel, BaseProcessor, ProcessorConfig
  build_pipeline_from_yaml, ProcessorRegistry, Pipeline
"""
from app.pipeline.message import (
    Message,
    RawTickPayload,
    CandlePayload,
    AMTResultPayload,
    SignalGatePayload,
    LLMDecisionPayload,
    OverseerDecisionPayload,
    OrderPayload,
    PositionEventPayload,
    RawTickMessage,
    CandleMessage,
    AMTResultMessage,
    SignalGateMessage,
    LLMDecisionMessage,
    OverseerDecisionMessage,
    OrderMessage,
    PositionEventMessage,
)
from app.pipeline.channel import Channel
from app.pipeline.processor import BaseProcessor, Processor, ProcessorConfig
from app.pipeline.registry import Pipeline, ProcessorRegistry, build_pipeline_from_yaml

__all__ = [
    # message types
    "Message",
    "RawTickPayload",
    "CandlePayload",
    "AMTResultPayload",
    "SignalGatePayload",
    "LLMDecisionPayload",
    "OverseerDecisionPayload",
    "OrderPayload",
    "PositionEventPayload",
    # typed message aliases
    "RawTickMessage",
    "CandleMessage",
    "AMTResultMessage",
    "SignalGateMessage",
    "LLMDecisionMessage",
    "OverseerDecisionMessage",
    "OrderMessage",
    "PositionEventMessage",
    # core infrastructure
    "Channel",
    "BaseProcessor",
    "Processor",
    "ProcessorConfig",
    "Pipeline",
    "ProcessorRegistry",
    "build_pipeline_from_yaml",
]
