"""Tool descriptor + spec types.

``ToolDescriptor`` is the MCP-ready metadata required for *every* tool (name,
description, input/output JSON schema, error behavior, auth requirement, ownership
boundary). ``ToolSpec`` bundles that metadata with the typed callable, so the same
definition serves the agent (in-process), the REST routes, and a future MCP server.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

AuthRequirement = Literal["none", "customer_scope"]


class ToolDescriptor(BaseModel):
    """MCP-ready metadata describing a tool to a calling model or operator."""

    name: str
    description: str
    input_schema: dict
    output_schema: dict
    error_behavior: str
    auth_requirement: AuthRequirement
    ownership_boundary: str


@dataclass(frozen=True)
class ToolSpec:
    """A tool: its typed contract, its callable, and its descriptor metadata."""

    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    func: Callable[[BaseModel], BaseModel]
    auth_requirement: AuthRequirement
    ownership_boundary: str
    error_behavior: str = "Returns a typed result; raises on infrastructure errors."
    is_empty: Callable[[BaseModel], bool] | None = None

    def descriptor(self) -> ToolDescriptor:
        """Build the MCP-ready descriptor from the Pydantic models' JSON schemas."""
        return ToolDescriptor(
            name=self.name,
            description=self.description,
            input_schema=self.input_model.model_json_schema(),
            output_schema=self.output_model.model_json_schema(),
            error_behavior=self.error_behavior,
            auth_requirement=self.auth_requirement,
            ownership_boundary=self.ownership_boundary,
        )
