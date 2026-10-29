from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user, require_user

router = APIRouter(prefix="/memos", tags=["memos"])


def _can_view(memo: models.Memo, user: models.User | None) -> bool:
    # 公开备忘：任何人（含未登录）可见
    if memo.is_public:
        return True
    # 私有备忘：仅作者本人登录后可见
    return user is not None and memo.owner_id == user.id


def _get_own_memo(memo_id: int, user: models.User, db: Session) -> models.Memo:
    memo = db.get(models.Memo, memo_id)
    if memo is None or memo.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memo not found")
    return memo


@router.get("", response_model=list[schemas.MemoOut])
def list_memos(
    db: Session = Depends(get_db),
    user: models.User | None = Depends(get_current_user),
):
    memos = db.query(models.Memo).order_by(models.Memo.created_at.desc()).all()
    return [m for m in memos if _can_view(m, user)]


@router.post("", response_model=schemas.MemoOut, status_code=status.HTTP_201_CREATED)
def create_memo(
    payload: schemas.MemoCreate,
    db: Session = Depends(get_db),
    user: models.User | None = Depends(get_current_user),
):
    user = require_user(user)
    memo = models.Memo(
        title=payload.title,
        content=payload.content,
        is_public=payload.is_public,
        owner_id=user.id,
    )
    db.add(memo)
    db.commit()
    db.refresh(memo)
    return memo


@router.get("/{memo_id}", response_model=schemas.MemoOut)
def get_memo(
    memo_id: int,
    db: Session = Depends(get_db),
    user: models.User | None = Depends(get_current_user),
):
    memo = db.get(models.Memo, memo_id)
    if memo is None or not _can_view(memo, user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memo not found")
    return memo


@router.put("/{memo_id}", response_model=schemas.MemoOut)
def update_memo(
    memo_id: int,
    payload: schemas.MemoUpdate,
    db: Session = Depends(get_db),
    user: models.User | None = Depends(get_current_user),
):
    user = require_user(user)
    memo = _get_own_memo(memo_id, user, db)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(memo, key, value)
    db.commit()
    db.refresh(memo)
    return memo


@router.delete("/{memo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memo(
    memo_id: int,
    db: Session = Depends(get_db),
    user: models.User | None = Depends(get_current_user),
):
    user = require_user(user)
    memo = _get_own_memo(memo_id, user, db)
    db.delete(memo)
    db.commit()
