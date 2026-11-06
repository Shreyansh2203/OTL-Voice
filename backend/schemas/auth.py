from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel


class LoginBody(BaseModel):
    username: str = ""
    personNumber: str = ""
    password: str = ""


class HasIdentity(Protocol):
    @property
    def username(self) -> str: ...

    @property
    def employee_id(self) -> str: ...

    @property
    def full_name(self) -> str: ...


def identity_dict(ctx_or_employee: HasIdentity) -> dict[str, Any]:
    return {
        "username": ctx_or_employee.username,
        "employeeId": ctx_or_employee.employee_id,
        "fullName": ctx_or_employee.full_name,
    }
