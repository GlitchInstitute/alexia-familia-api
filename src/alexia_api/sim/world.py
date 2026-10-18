"""The synthetic families that the simulator serves. Every name here is invented."""

from dataclasses import dataclass, field
from typing import Final

SIM_INSTITUTION_KEY: Final = "demo-school"
DEMO_USER_A: Final = "marta.ejemplo"
DEMO_PASSWORD_A: Final = "demo-password-a"
DEMO_USER_B: Final = "pablo.prueba"
DEMO_PASSWORD_B: Final = "demo-password-b"


def synthetic_guid(number: int) -> str:
    """A well-formed GUID that is plainly not real, `5afe0000-0000-4000-8000-<number in hex>`."""
    return f"5afe0000-0000-4000-8000-{number:012x}"


@dataclass(frozen=True, slots=True)
class SimStaff:
    id: str
    name: str
    role: str


@dataclass(frozen=True, slots=True)
class SimTracking:
    tasks: int = 0
    activities: int = 0
    notes: int = 0
    tests: int = 0
    incidents: int = 0


@dataclass(frozen=True, slots=True)
class SimChild:
    student_id: str
    person_id: str
    full_name: str
    first_name: str
    relation: str
    tracking: SimTracking = field(default_factory=SimTracking)
    staff: tuple[SimStaff, ...] = ()


@dataclass(frozen=True, slots=True)
class SimGuardian:
    person_id: str
    first_name: str


@dataclass(frozen=True, slots=True)
class SimFamily:
    username: str
    password: str
    guardian: SimGuardian
    children: tuple[SimChild, ...]


@dataclass(frozen=True, slots=True)
class SimWorld:
    institution_key: str
    families: tuple[SimFamily, ...]

    def family_for(self, username: str) -> SimFamily | None:
        return next((family for family in self.families if family.username == username), None)


def default_world() -> SimWorld:
    """Two families with two children each, so tests and demos cover several accounts and kids."""
    tutor_a = SimStaff(synthetic_guid(0x601), "Ana Muestra Tutora", "Tutora")
    maths = SimStaff(synthetic_guid(0x602), "Carlos Ejemplo Profesor", "Matemáticas")
    tutor_b = SimStaff(synthetic_guid(0x603), "Rosa Prueba Tutora", "Tutora")
    music = SimStaff(synthetic_guid(0x604), "Tomás Demo Profesor", "Música")

    family_a = SimFamily(
        username=DEMO_USER_A,
        password=DEMO_PASSWORD_A,
        guardian=SimGuardian(person_id=synthetic_guid(0x301), first_name="Marta"),
        children=(
            SimChild(
                student_id=synthetic_guid(0x101),
                person_id=synthetic_guid(0x201),
                full_name="Lucía Ejemplo Muestra",
                first_name="Lucía",
                relation="Hija",
                tracking=SimTracking(tasks=3, activities=1, notes=0, tests=2, incidents=0),
                staff=(tutor_a, maths),
            ),
            SimChild(
                student_id=synthetic_guid(0x102),
                person_id=synthetic_guid(0x202),
                full_name="Mateo Ejemplo Muestra",
                first_name="Mateo",
                relation="Hijo",
                tracking=SimTracking(tasks=1, activities=0, notes=2, tests=0, incidents=1),
                staff=(tutor_b, music),
            ),
        ),
    )
    family_b = SimFamily(
        username=DEMO_USER_B,
        password=DEMO_PASSWORD_B,
        guardian=SimGuardian(person_id=synthetic_guid(0x311), first_name="Pablo"),
        children=(
            SimChild(
                student_id=synthetic_guid(0x111),
                person_id=synthetic_guid(0x211),
                full_name="Hugo Prueba Demo",
                first_name="Hugo",
                relation="Hijo",
                tracking=SimTracking(tasks=5, activities=2, notes=1, tests=1, incidents=0),
                staff=(tutor_a, music),
            ),
            SimChild(
                student_id=synthetic_guid(0x112),
                person_id=synthetic_guid(0x212),
                full_name="Alba Prueba Demo",
                first_name="Alba",
                relation="Hija",
                tracking=SimTracking(tasks=0, activities=3, notes=0, tests=0, incidents=2),
                staff=(tutor_b, maths),
            ),
        ),
    )
    return SimWorld(institution_key=SIM_INSTITUTION_KEY, families=(family_a, family_b))
