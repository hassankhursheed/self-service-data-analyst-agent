"""Feedback on answers: a user rates their own question (brief §16).

One rating per user and question; sending again updates it and reopens the review.
The admin review queue (not-helpful answers) is built on this in Step 20.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import AuthenticatedUser
from app.core.enums import Rating, ReviewStatus
from app.core.errors import AppError
from app.core.masking import mask_text
from app.db.models import Feedback, Question


class QuestionNotFound(AppError):
    code = "NOT_FOUND"
    user_message = "Question not found."


class FeedbackService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def rate(
        self, user: AuthenticatedUser, question_id: uuid.UUID, rating: Rating,
        comment: str | None = None,
    ) -> Feedback:  # fmt: skip
        async with self.sessions() as session, session.begin():
            question = await session.get(Question, question_id)
            if question is None or question.user_id != user.user_id:
                raise QuestionNotFound(f"question {question_id} not found for this user")
            feedback = await session.scalar(
                select(Feedback).where(
                    Feedback.question_id == question_id, Feedback.user_id == user.user_id
                )
            )
            if feedback is None:
                feedback = Feedback(question_id=question_id, user_id=user.user_id)
                session.add(feedback)
            feedback.rating = rating.value
            feedback.comment = mask_text(comment.strip()) if comment and comment.strip() else None
            feedback.review_status = ReviewStatus.OPEN.value
            await session.flush()
            return feedback
