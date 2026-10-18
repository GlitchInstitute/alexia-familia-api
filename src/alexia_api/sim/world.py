"""The synthetic families that the simulator serves. Every name here is invented."""

from dataclasses import dataclass, field
from typing import Final

from alexia_api.sim.mail import SimMessage

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
    messages: tuple[SimMessage, ...] = ()


@dataclass(frozen=True, slots=True)
class SimWorld:
    institution_key: str
    families: tuple[SimFamily, ...]

    def family_for(self, username: str) -> SimFamily | None:
        return next((family for family in self.families if family.username == username), None)


def _received(
    number: int,
    sender: str,
    subject: str,
    sent_at: str,
    *,
    read: bool = True,
    expires: str | None = None,
    category: str = "",
    institutional: bool = False,
) -> SimMessage:
    date, time = sent_at.split(" ")
    return SimMessage(
        guid=synthetic_guid(number),
        folder="received",
        sender=sender,
        subject=subject,
        date=date,
        time=time,
        body_html=f"<p>{subject.strip()}. Texto de ejemplo para las familias.</p>",
        read=read,
        expires=expires,
        category=category,
        institutional=institutional,
    )


def _sent(number: int, sender: str, subject: str, sent_at: str) -> SimMessage:
    date, time = sent_at.split(" ")
    return SimMessage(
        guid=synthetic_guid(number),
        folder="sent",
        sender=sender,
        subject=subject,
        date=date,
        time=time,
        body_html=f"<p>{subject}. Texto de ejemplo enviado por la familia.</p>",
    )


def _mail_of_marta() -> tuple[SimMessage, ...]:
    ana, carlos = "Ana Muestra Tutora", "Carlos Ejemplo Profesor"
    return (
        _received(
            0x1001, ana, "Reto de matemáticas", "2026-10-15 09:12", read=False, category="Aviso"
        ),
        _received(
            0x1002,
            "Secretaría",
            "  Excursión al museo  ",
            "2026-10-14 17:40",
            expires="2026-10-25",
            category="Encuesta",
        ),
        _received(0x1003, carlos, "Horario de octubre", "2026-10-13 08:05", read=False),
        _received(0x1004, ana, "Entrevista de tutoría", "2026-10-10 12:00", category="Entrevistas"),
        _received(
            0x1005, "Dirección", "Calendario escolar", "2026-10-05 10:30", institutional=True
        ),
        _received(0x1006, "Comedor", "Menú de octubre", "2026-09-30 11:00"),
        _received(0x1007, ana, "Reunión de padres", "2026-09-20 16:20"),
        _received(
            0x1008, "Secretaría", "Bienvenida al curso", "2026-09-12 09:00", institutional=True
        ),
        _sent(0x2001, "Marta", "Ausencia de Lucía", "2026-10-01 20:15"),
        _sent(0x2002, "Marta", "Consulta sobre la excursión", "2026-09-15 18:00"),
    )


def _mail_of_pablo() -> tuple[SimMessage, ...]:
    return (
        _received(0x1101, "Rosa Prueba Tutora", "Bienvenida al curso", "2026-09-10 09:30"),
        _received(0x1102, "Tomás Demo Profesor", "Ensayo del coro", "2026-10-12 13:15", read=False),
        _received(0x1103, "Secretaría", "Recibo de octubre", "2026-10-02 10:00"),
        _sent(0x2101, "Pablo", "Cambio de autorización", "2026-10-03 19:45"),
    )


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
        messages=_mail_of_marta(),
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
        messages=_mail_of_pablo(),
    )
    return SimWorld(institution_key=SIM_INSTITUTION_KEY, families=(family_a, family_b))
