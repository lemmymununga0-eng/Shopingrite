"""Request/response models for the store (products, cart, orders, inventory)."""
import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
_PHONE = re.compile(r"^(?:\+?260|0)([279]\d{8})$")      # Zambian mobile or landline, normalised to +260
_POSTAL = re.compile(r"^[A-Za-z0-9 -]{3,12}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _clean(value: str) -> str:
    return _CONTROL.sub(" ", value).strip()


StockStatus = Literal["in_stock", "low_stock", "out_of_stock"]


class CategoryOut(BaseModel):
    id: int
    slug: str
    name: str
    product_count: int


class ProductOut(BaseModel):
    id: int
    sku: str
    name: str
    description: str
    category_slug: str
    category_name: str
    price_cents: int
    offer_price_cents: int | None
    effective_price_cents: int
    currency: str
    unit: str
    image_ref: str
    image_alt: str = ""
    image_status: str = "placeholder"
    image_source: str = ""
    image_license: str = ""
    brand: str = ""
    pack_size: str = ""
    price_status: str = "estimated"
    price_source_name: str = ""
    price_source_url: str = ""
    price_source_type: str = ""
    price_checked_on: date | None = None
    offer_ends_on: date | None = None
    is_featured: bool
    is_demo: bool
    stock_status: StockStatus
    available_quantity: int


class ProductPage(BaseModel):
    items: list[ProductOut]
    total: int
    page: int
    page_size: int


class InventoryOut(BaseModel):
    product_id: int
    sku: str
    name: str
    category_slug: str
    available_quantity: int
    reserved_quantity: int
    reorder_threshold: int
    stock_status: StockStatus
    below_reorder_threshold: bool
    updated_at: datetime


class InventoryPage(BaseModel):
    items: list[InventoryOut]
    total: int
    page: int
    page_size: int


class InventoryAdjust(BaseModel):
    """Exactly one of `set_available` / `delta`. A reason is mandatory and goes in the audit trail."""
    model_config = ConfigDict(extra="forbid")
    set_available: int | None = Field(default=None, ge=0, le=1_000_000)
    delta: int | None = Field(default=None, ge=-1_000_000, le=1_000_000)
    reorder_threshold: int | None = Field(default=None, ge=0, le=100_000)
    reason: str = Field(min_length=3, max_length=300)


class CartAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: int = Field(ge=1)
    quantity: int = Field(default=1, ge=1, le=1000)


class CartUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quantity: int = Field(ge=1, le=1000)


class CartLine(BaseModel):
    item_id: int
    product: ProductOut
    quantity: int
    line_total_cents: int
    issue: Literal["unavailable", "out_of_stock", "quantity_exceeds_stock"] | None = None
    issue_message: str | None = None


class CartOut(BaseModel):
    items: list[CartLine]
    item_count: int
    subtotal_cents: int
    currency: str
    has_issues: bool
    delivery_fee_cents: int
    delivery_fee_note: str


class Contact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(max_length=254)
    phone: str

    @field_validator("name")
    @classmethod
    def _name_ok(cls, v: str) -> str:
        return _clean(v)

    @field_validator("email")
    @classmethod
    def _email_ok(cls, v: str) -> str:
        v = _clean(v)
        if not _EMAIL.match(v):
            raise ValueError("enter a valid email address")
        return v

    @field_validator("phone")
    @classmethod
    def _phone_ok(cls, v: str) -> str:
        digits = re.sub(r"[\s().-]", "", _clean(v))
        m = _PHONE.match(digits)
        if not m:
            raise ValueError("enter a valid Zambian phone number, for example 0971 234 567 or +260 971 234 567")
        return "+260" + m.group(1)


class Address(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line: str = Field(min_length=5, max_length=200)
    city: str = Field(min_length=2, max_length=80)
    postal_code: str = ""

    @field_validator("line", "city")
    @classmethod
    def _text_ok(cls, v: str) -> str:
        return _clean(v)

    @field_validator("postal_code")
    @classmethod
    def _postal_ok(cls, v: str) -> str:
        v = _clean(v)
        if v and not _POSTAL.match(v):
            raise ValueError("enter a valid postal code or leave it empty")
        return v


class PaymentChoice(BaseModel):
    """Which payment method to use. There is deliberately no field for card numbers, PINs or one-time codes;
    `extra="forbid"` makes the API reject any attempt to send some. `scenario` is honoured only by the simulated
    provider (the controlled demonstration)."""
    model_config = ConfigDict(extra="forbid")
    method: Literal["simulated", "cod", "airtel_money", "mtn_momo", "card"] = "simulated"
    scenario: Literal["success", "failure", "pending", "cancelled", "action_required"] = "success"


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fulfilment: Literal["delivery", "collection"]
    contact: Contact
    address: Address | None = None
    area: str | None = Field(default=None, max_length=80)
    delivery_instructions: str | None = Field(default=None, max_length=300)
    payment: PaymentChoice = PaymentChoice()

    @field_validator("area", "delivery_instructions")
    @classmethod
    def _opt_text(cls, v):
        return _clean(v) if v else v


class OrderItemOut(BaseModel):
    product_id: int
    sku: str
    name: str
    unit_price_cents: int
    quantity: int
    line_total_cents: int


class PaymentAttemptOut(BaseModel):
    reference: str
    method: str
    provider: str
    mode: str
    status: str
    amount_cents: int
    currency: str
    failure_reason: str
    created_at: datetime
    updated_at: datetime


class OrderOut(BaseModel):
    id: str
    reference: str
    user_id: str
    status: str
    fulfilment: str
    contact_name: str
    contact_email: str
    contact_phone: str
    address_line: str
    city: str
    postal_code: str
    area: str = ""
    delivery_instructions: str = ""
    items: list[OrderItemOut]
    subtotal_cents: int
    delivery_fee_cents: int
    total_cents: int
    currency: str
    payment_mode: str
    payment_method: str = "simulated"
    payment_status: str
    payment_due_at: datetime | None = None
    payment_notice: str
    payment_attempts: list[PaymentAttemptOut] = []
    created_at: datetime
    updated_at: datetime


class OrderPage(BaseModel):
    items: list[OrderOut]
    total: int
    page: int
    page_size: int


class OrderStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["picking", "ready", "out_for_delivery", "completed", "cancelled"]
