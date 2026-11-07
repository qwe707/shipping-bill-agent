from pydantic import BaseModel, ConfigDict, Field

FIELDS = ['document_type','reference_no','date','issuer','recipient','charge_item','amount','currency','payment_term','quantity','unit_price','subtotal','tax','total','bl_no','booking_no','container_no','payer','payee']
NUMBERS = {'amount','quantity','unit_price','subtotal','tax','total'}

class Chunk(BaseModel):
    id: str
    name: str
    text: str
    locator: str
    source_method: str

class Evidence(BaseModel):
    model_config = ConfigDict(extra='forbid')
    chunk_id: str
    quote: str

class Update(BaseModel):
    model_config = ConfigDict(extra='forbid')
    field: str
    chunk_id: str
    quote: str

class FeeRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')
    document_type: str | None = None
    reference_no: str | None = None
    date: str | None = None
    issuer: str | None = None
    recipient: str | None = None
    charge_item: str | None = None
    amount: str | None = None
    currency: str | None = None
    payment_term: str | None = None
    quantity: str | None = None
    unit_price: str | None = None
    subtotal: str | None = None
    tax: str | None = None
    total: str | None = None
    bl_no: str | None = None
    booking_no: str | None = None
    container_no: str | None = None
    payer: str | None = None
    payee: str | None = None
    evidence: dict[str, Evidence] = Field(default_factory=dict)
    explicit_updates: list[Update] = Field(default_factory=list)

class Extraction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    records: list[FeeRecord]
