import pytest
from pydantic import ValidationError

from app.schemas.service_request import ServiceRequestCreate


def make_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "contact": "dev@example.com",
        "description": "Нужен лендинг для IT-услуг с формой заявки.",
        "source_site": "main-landing",
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    "contact",
    ["dev@example.com", "+374 99 123 456", "@demo_user"],
)
def test_accepts_supported_contact_types(contact: str) -> None:
    request = ServiceRequestCreate(**make_payload(contact=contact))
    assert request.contact == contact


@pytest.mark.parametrize("contact", ["not-a-contact", "@ab", "123", "name@", "+---"])
def test_rejects_invalid_contact(contact: str) -> None:
    with pytest.raises(ValidationError):
        ServiceRequestCreate(**make_payload(contact=contact))


def test_optional_empty_fields_are_normalized_to_none() -> None:
    request = ServiceRequestCreate(**make_payload(name="  ", budget=""))
    assert request.name is None
    assert request.budget is None


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ServiceRequestCreate(**make_payload(unexpected="value"))


def test_description_must_be_long_enough() -> None:
    with pytest.raises(ValidationError):
        ServiceRequestCreate(**make_payload(description="Коротко"))
