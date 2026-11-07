"""Questions, clarifications, conversations and feedback (logged-in users)."""

import uuid

from fastapi import APIRouter, Request

from app.agent.response import build_response
from app.agent.state import AgentState
from app.api.deps import CorrelationId, PagingDep, ServicesDep
from app.api.errors import ApiError, error_responses
from app.api.schemas import (
    AskRequest,
    AskResponse,
    ClarifyRequest,
    ConversationDetailResponse,
    ConversationList,
    FeedbackRequest,
    FeedbackResponse,
)
from app.auth.dependencies import CurrentUser
from app.core.enums import BlockReason, QuestionStatus

router = APIRouter(tags=["questions"])
ERRORS = error_responses(400, 401, 403, 404, 409, 429, 500)

# Rejections that are request problems, not agent outcomes: they become HTTP errors, but
# only after the agent has run, so every one of them is still audited (N-11).
HTTP_REJECTIONS: dict[BlockReason, str] = {
    BlockReason.NO_ROLE: "NO_ROLE",  # 403
    BlockReason.ADMIN_NO_BUSINESS_DATA: "ADMIN_ONLY",  # 403
    BlockReason.USER_DISABLED: "INVALID_TOKEN",  # 401
    BlockReason.QUESTION_EMPTY: "QUESTION_EMPTY",  # 400
    BlockReason.QUESTION_TOO_LONG: "QUESTION_TOO_LONG",  # 400
}


async def _ask_response(
    services: ServicesDep, state: AgentState, conversation_id: uuid.UUID
) -> AskResponse:
    if state.status is QuestionStatus.REJECTED and state.block_reason in HTTP_REJECTIONS:
        raise ApiError(
            HTTP_REJECTIONS[state.block_reason],
            state.user_message or "This request is not allowed.",
        )
    response = build_response(state)
    return AskResponse(
        **response.model_dump(),
        conversation_id=conversation_id,
        question_id=await services.conversations.question_id_for(state),
    )


@router.post("/ask", response_model=AskResponse, responses=ERRORS)
async def ask(
    body: AskRequest, user: CurrentUser, services: ServicesDep, correlation_id: CorrelationId
) -> AskResponse:
    services.question_limiter.check(f"user:{user.user_id}")
    conversation_id = body.conversation_id
    if conversation_id is None:
        conversation_id = await services.conversations.start_conversation(user, body.question)
    state = await services.conversations.ask(
        user, body.question, conversation_id, correlation_id=correlation_id
    )
    return await _ask_response(services, state, conversation_id)


@router.post("/clarify", response_model=AskResponse, responses=ERRORS)
async def clarify(
    body: ClarifyRequest, user: CurrentUser, services: ServicesDep, request: Request
) -> AskResponse:
    services.question_limiter.check(f"user:{user.user_id}")
    state = await services.conversations.clarify(user, body.conversation_id, body.answer)
    # The resumed run keeps its question's correlation ID; use it for this response too,
    # so header, body, audit rows and trace all match.
    if state.correlation_id is not None:
        request.state.correlation_id = state.correlation_id
    return await _ask_response(services, state, body.conversation_id)


@router.get("/conversations", response_model=ConversationList, responses=ERRORS)
async def list_conversations(
    user: CurrentUser, services: ServicesDep, paging: PagingDep, correlation_id: CorrelationId
) -> ConversationList:
    items = await services.conversations.list_conversations(user)
    return ConversationList(
        correlation_id=correlation_id, items=paging.window(items), total=len(items),
        page=paging.page, page_size=paging.page_size,
    )  # fmt: skip


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse,
            responses=ERRORS)  # fmt: skip
async def get_conversation(
    conversation_id: uuid.UUID, user: CurrentUser, services: ServicesDep,
    correlation_id: CorrelationId,
) -> ConversationDetailResponse:  # fmt: skip
    detail = await services.conversations.open_conversation(user, conversation_id)
    latest = await services.conversations.latest_state(user, conversation_id)
    return ConversationDetailResponse(
        correlation_id=correlation_id,
        id=detail.id,
        title=detail.title,
        questions=detail.questions,
        latest=build_response(latest) if latest is not None and latest.status else None,
    )


@router.post("/feedback", response_model=FeedbackResponse, responses=ERRORS)
async def feedback(
    body: FeedbackRequest, user: CurrentUser, services: ServicesDep, correlation_id: CorrelationId
) -> FeedbackResponse:
    saved = await services.feedback.rate(user, body.question_id, body.rating, body.comment)
    return FeedbackResponse(correlation_id=correlation_id, feedback_id=saved.id, rating=body.rating)
