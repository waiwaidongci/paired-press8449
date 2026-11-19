from pydantic import BaseModel,Field
class HoldoutInput(BaseModel):
    source_key:str=Field(min_length=1,max_length=100)
    values:dict
class GateInput(BaseModel):
    threshold:float=Field(ge=-1000000000,le=1000000000)
