"""Pydantic models for request/response."""

from pydantic import BaseModel
from typing import Optional, Any


# -- Wrapper responses (match original {"ok": true/false, ...} format) --

class OkResponse(BaseModel):
    ok: bool = True
    data: Optional[Any] = None


class ErrorResponse(BaseModel):
    ok: bool = False
    error: str


# -- Auth --

class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


# -- Projects --

class ProjectCreate(BaseModel):
    name: str = ""
    description: str = ""
    color: str = "#6366f1"


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None


# -- Channels --

class ChannelCreate(BaseModel):
    project_id: str
    name: str = ""
    icon: str = "#"
    color: str = "#6366f1"


class ChannelUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None


# -- Messages --

class MessageCreate(BaseModel):
    channel_id: str
    text: str = ""
    image: str = ""
    bot_id: Optional[str] = None


class MessageUpdate(BaseModel):
    text: Optional[str] = None


# -- Threads --

class ThreadCreate(BaseModel):
    message_id: str
    text: str = ""
    bot_id: Optional[str] = None


# -- Tasks --

class TaskCreate(BaseModel):
    project_id: str
    channel_id: Optional[str] = None
    status: str = "todo"
    title: str = ""
    description: str = ""
    milestone_id: Optional[str] = None
    deadline: Optional[int] = None


class TaskUpdate(BaseModel):
    status: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    milestone_id: Optional[str] = None
    deadline: Optional[int] = None
    channel_id: Optional[str] = None


# -- Milestones --

class MilestoneCreate(BaseModel):
    project_id: str
    name: str = ""
    deadline: Optional[int] = None
    color: str = "#6366f1"


class MilestoneUpdate(BaseModel):
    name: Optional[str] = None
    deadline: Optional[int] = None
    color: Optional[str] = None


# -- Team Members --

class MemberCreate(BaseModel):
    project_id: str
    name: str = ""
    role: str = "멤버"
    avatar_color: str = "#6366f1"


class MemberUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    avatar_color: Optional[str] = None


# -- Bots --

class BotCreate(BaseModel):
    project_id: Optional[str] = None
    name: str = ""
    role: str = ""
    avatar: str = "🤖"
    system_prompt: str = ""
    is_active: bool = True


class BotUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    avatar: Optional[str] = None
    system_prompt: Optional[str] = None
    is_active: Optional[int] = None
    project_id: Optional[str] = None


# -- Settings --

class SettingsUpdate(BaseModel):
    gateway_url: Optional[str] = None
    gateway_token: Optional[str] = None
    context_length: Optional[int] = None
    theme: Optional[str] = None
