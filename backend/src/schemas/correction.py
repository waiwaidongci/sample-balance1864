from typing import Literal,Optional
from pydantic import BaseModel,Field
class CorrectionInput(BaseModel):
    code:str=Field(min_length=2,max_length=60,pattern=r'^[A-Za-z0-9_-]+$')
    depends_on:Optional[str]=Field(default=None,max_length=60,pattern=r'^[A-Za-z0-9_-]+$')
    base_version:Optional[int]=Field(default=None,ge=1)
    csv_text:str=Field(min_length=10,max_length=1000000)
class ResolutionItem(BaseModel):
    conflict_id:int
    choice:Literal['incoming','current','value']
    value:Optional[str]=Field(default=None,max_length=60)
class ResolveInput(BaseModel):
    resolutions:list[ResolutionItem]=Field(min_length=1,max_length=5000)
