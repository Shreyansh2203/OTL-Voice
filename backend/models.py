from dataclasses import dataclass


@dataclass
class Employee:
    """Represents the authenticated employee for session context."""
    employee_id: str  # Maps to Employee_Number_c
    username: str     # Typically the same as employee_id
    full_name: str    # Maps to Employee_Name_c
