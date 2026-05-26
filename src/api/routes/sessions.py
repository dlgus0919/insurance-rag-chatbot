"""Persisted chat session routes."""

from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db import get_db
from src.api.deps import require_permission
from src.api.exceptions import InvalidFormatException, SessionNotFoundException
from src.api.models import ChatMessage, ChatSession
from src.api.rate_limit import limiter
from src.api.schemas.sessions import MessageResponse, SessionCreateRequest, SessionResponse
from src.auth.users import User

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionResponse])
async def list_sessions(
    user: User = Depends(require_permission("sessions.read")),
    db: AsyncSession = Depends(get_db),
) -> list[SessionResponse]:
    """Return only the authenticated user's chat sessions."""

    count_subquery = (
        select(ChatMessage.session_id, func.count(ChatMessage.id).label("message_count"))
        .group_by(ChatMessage.session_id)
        .subquery()
    )
    result = await db.execute(
        select(ChatSession, func.coalesce(count_subquery.c.message_count, 0))
        .outerjoin(count_subquery, ChatSession.id == count_subquery.c.session_id)
        .where(ChatSession.user_id == user.username)
        .order_by(ChatSession.created_at.desc())
    )
    return [
        SessionResponse(
            id=session.id,
            title=session.title,
            created_at=session.created_at,
            message_count=int(message_count or 0),
        )
        for session, message_count in result.all()
    ]


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    request: SessionCreateRequest | None = None,
    user: User = Depends(require_permission("chat.stream")),
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Create a new user-owned chat session."""

    payload = request or SessionCreateRequest()
    chat_session = ChatSession(user_id=user.username, title=payload.title or "새로운 보상 질의")
    db.add(chat_session)
    await db.commit()
    await db.refresh(chat_session)
    return SessionResponse(
        id=chat_session.id,
        title=chat_session.title,
        created_at=chat_session.created_at,
        message_count=0,
    )


@router.get("/{session_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    session_id: str,
    user: User = Depends(require_permission("sessions.read")),
    db: AsyncSession = Depends(get_db),
) -> list[MessageResponse]:
    """Return all messages for a user-owned session in chronological order."""

    await _require_owned_session(db, user.username, session_id)
    result = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc())
    )
    return [
        MessageResponse(
            id=message.id,
            session_id=message.session_id,
            role=message.role,
            content=message.content,
            sources=message.sources,
            created_at=message.created_at,
        )
        for message in result.scalars()
    ]


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    user: User = Depends(require_permission("sessions.delete")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a user-owned session and cascade its messages."""

    await _require_owned_session(db, user.username, session_id)
    await db.execute(delete(ChatSession).where(ChatSession.id == session_id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{session_id}/export")
@limiter.limit("10/hour")
async def export_session(
    request: Request,
    session_id: str,
    fmt: str = "txt",
    user: User = Depends(require_permission("sessions.export")),
    db: AsyncSession = Depends(get_db),
):
    """Export a user-owned chat session as txt, csv, or json."""

    if fmt not in {"txt", "csv", "json"}:
        raise InvalidFormatException(detail="fmt는 txt, csv, json 중 하나여야 합니다.")

    chat_session = await _require_owned_session(db, user.username, session_id)
    result = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc())
    )
    messages = list(result.scalars())
    filename = f"chat_{session_id}.{fmt}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

    if fmt == "json":
        return Response(
            content=json.dumps(
                {
                    "session_id": chat_session.id,
                    "title": chat_session.title,
                    "created_at": chat_session.created_at.isoformat(),
                    "messages": [
                        {
                            "timestamp": message.created_at.isoformat(),
                            "role": message.role,
                            "content": message.content,
                            "sources": message.sources or [],
                        }
                        for message in messages
                    ],
                },
                ensure_ascii=False,
            ),
            media_type="application/json; charset=utf-8",
            headers=headers,
        )

    if fmt == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["timestamp", "role", "content", "sources"])
        for message in messages:
            writer.writerow(
                [
                    message.created_at.isoformat(),
                    message.role,
                    message.content,
                    _format_sources(message.sources or []),
                ]
            )
        return Response(buffer.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)

    content = _format_txt_export(chat_session, messages)
    return Response(content, media_type="text/plain; charset=utf-8", headers=headers)


async def _require_owned_session(db: AsyncSession, username: str, session_id: str) -> ChatSession:
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == username)
    )
    chat_session = result.scalar_one_or_none()
    if chat_session is None:
        raise SessionNotFoundException(detail=f"session_id={session_id}")
    return chat_session


def _format_txt_export(chat_session: ChatSession, messages: list[ChatMessage]) -> str:
    lines = [
        "=== 신한EZ손해보험 채팅 기록 ===",
        f"생성일: {chat_session.created_at.date().isoformat()}",
        f"세션: {chat_session.title}",
        "",
    ]
    for message in messages:
        speaker = "사용자" if message.role == "user" else "봇"
        lines.extend(
            [
                f"[{message.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {speaker}",
                f"> {message.content}",
            ]
        )
        sources = _format_sources(message.sources or [])
        if sources:
            lines.append(f"출처: {sources}")
        lines.append("")
    return "\n".join(lines)


def _format_sources(sources: list[dict]) -> str:
    formatted = []
    for source in sources:
        filename = source.get("filename") or source.get("source") or source.get("title") or "출처"
        page = source.get("page")
        score = source.get("score")
        text = str(filename)
        if page is not None:
            text += f" (p.{page})"
        if score is not None:
            text += f" score={score}"
        formatted.append(text)
    return "; ".join(formatted)
