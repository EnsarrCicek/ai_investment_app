from pydantic import BaseModel


class IpoNoteCreate(BaseModel):
    company_name: str
    bist_code: str | None = None
    note_text: str
