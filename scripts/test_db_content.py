from sqlmodel import Session, select

from app.database import engine
from app.models import RawDocument

with Session(engine) as session:
    docs = session.exec(select(RawDocument).order_by(RawDocument.fetched_at.desc())).all()
    print(f"Total documents: {len(docs)}\n")
    for d in docs:
        print(f"[{d.source_type.upper()}] {d.title[:70]}")
        print(f"  URL:      {d.source_url[:80]}")
        print(f"  Language: {d.language} | Chars: {len(d.raw_text or '')}")
        print(f"  Preview:  {(d.raw_text or '')[:150].strip()}")
        print()

