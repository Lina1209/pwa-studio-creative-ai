class FinanceRoleGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: UUID
    role_code: Literal[
        "finance_operator", "finance_approver", "finance_executor",
        "support_readonly", "auditor_readonly",
    ]
    scope_key: str = Field(min_length=1, max_length=200)
    valid_until: datetime
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("scope_key", "reason")
    @classmethod
    def reject_untrimmed_values(cls, value):
        if value.strip() != value or not value:
            raise ValueError("Value must be trimmed and non-empty.")
        return value

    @field_validator("valid_until")
    @classmethod
    def expiry_must_be_timezone_aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Finance role expiry must include a timezone.")
        return value


class FinanceRoleRevocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def reject_untrimmed_reason(cls, value: str) -> str:
        if value.strip() != value or not value:
            raise ValueError("Reason must be trimmed and non-empty.")
        return value
