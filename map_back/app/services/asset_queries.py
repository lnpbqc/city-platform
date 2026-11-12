from datetime import timezone

from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from app.cruds import assets as asset_records
from app.errors import ApiProblem
from app.services.assets import asset_record
from app.services.builtin_assets import RETIRED_ASSET_IDS


def list_assets(session: Session, page: int | None, page_size: int | None, kind: str | None,
                status: str | None, q: str | None, from_time: AwareDatetime | None,
                to_time: AwareDatetime | None, sort: str | None):
    start = from_time.astimezone(timezone.utc).replace(tzinfo=None) if from_time else None
    end = to_time.astimezone(timezone.utc).replace(tzinfo=None) if to_time else None
    if start and end and start > end:
        raise ApiProblem(422, "VALIDATION_ERROR", "from 不能晚于 to")
    paginated = page is not None or page_size is not None
    if paginated:
        page, page_size = page or 1, page_size or 20
    records, total = asset_records.query_assets(session, RETIRED_ASSET_IDS, kind=kind, status=status,
        q=q, start=start, end=end, sort=sort, page=page, page_size=page_size)
    inspect_files = not (paginated or kind or status or (q and q.strip()) or start or end or sort is not None)
    items = [asset_record(session, asset, inspect_files=inspect_files) for asset in records]
    return {"items": items, "total": total, "page": page, "page_size": page_size} if paginated else items
