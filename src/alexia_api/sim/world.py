"""The synthetic families that the simulator serves. Every name here is invented."""

from dataclasses import dataclass, field
from typing import Final

from alexia_api.sim.absences import SimAbsence
from alexia_api.sim.agenda import SimOccasion, SimSlot
from alexia_api.sim.mail import SimFile, SimMessage, SimTranslation

SIM_INSTITUTION_KEY: Final = "demo-school"
DEMO_USER_A: Final = "marta.ejemplo"
DEMO_PASSWORD_A: Final = "demo-password-a"
DEMO_USER_B: Final = "pablo.prueba"
DEMO_PASSWORD_B: Final = "demo-password-b"


def synthetic_guid(number: int) -> str:
    """A well-formed GUID that is plainly not real, `5afe0000-0000-4000-8000-<number in hex>`."""
    return f"5afe0000-0000-4000-8000-{number:012x}"


MUSEUM_FORM_FILE_ID: Final = f"{synthetic_guid(0xA01)}/autorizacion museo.pdf"
"""The portal's id for the permission slip of the museum trip, the file the demo shows."""


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
    timetable: tuple[SimSlot, ...] = ()
    events: tuple[SimOccasion, ...] = ()
    absences: tuple[SimAbsence, ...] = ()


@dataclass(frozen=True, slots=True)
class SimGuardian:
    person_id: str
    first_name: str
    interviews: tuple[SimOccasion, ...] = ()


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
    calendar: tuple[SimOccasion, ...] = ()

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
    anonymous: bool = False,
    body: str | None = None,
    files: tuple[SimFile, ...] = (),
    child_names: str = "",
    can_reply: bool = True,
    translations: tuple[SimTranslation, ...] = (),
) -> SimMessage:
    date, time = sent_at.split(" ")
    return SimMessage(
        guid=synthetic_guid(number),
        folder="received",
        sender=sender,
        subject=subject,
        date=date,
        time=time,
        body_html=body or f"<p>{subject.strip()}. Texto de ejemplo para las familias.</p>",
        read=read,
        expires=expires,
        category=category,
        institutional=institutional,
        anonymous=anonymous,
        files=files,
        child_names=child_names,
        can_reply=can_reply,
        translations=translations,
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


_PDF: Final = b"%PDF-1.4\n% Archivo de ejemplo\n%%EOF\n"
_PIXEL: Final = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGOYc+QJAAREAkXOJA2qAAAAAElFTkSuQmCC"
)
_MATH_CHALLENGE: Final = (
    "<p>Hola familias,</p>"
    "<p>Esta semana proponemos un <strong>reto de matemáticas</strong> para casa.</p>"
    "<ul><li>Resolver los tres problemas de la ficha.</li>"
    "<li>Entregar la hoja el viernes.</li></ul>"
    '<p>Hay un vídeo de apoyo en <a href="https://www.youtube.com/watch?v=ejemplo">este enlace</a>.'
    "</p>"
)
_MUSEUM_TRIP: Final = (
    "<p>Adjuntamos la autorización para la excursión al museo.</p>"
    "<p>Por favor, responda a la encuesta antes del 25 de octubre en "
    '<a href="https://forms.office.com/r/ejemplo">este formulario</a>.</p>'
)
_OCTOBER_TIMETABLE: Final = (
    "<p>El horario de octubre es el siguiente.</p>"
    "<table><tr><th>Día</th><th>Clase</th></tr>"
    "<tr><td>Lunes</td><td>Matemáticas</td></tr>"
    "<tr><td>Miércoles</td><td>Música</td></tr></table>"
)
_TUTORING_CALL: Final = (
    "<p>La entrevista será por videollamada el jueves a las 17:00.</p>"
    "<p>Enlace de la sala: https://meet.google.com/abc-defg-hij</p>"
    "<p>Si no puede conectarse, escriba a tutoria@example.test.</p>"
)
_SCHOOL_CALENDAR: Final = (
    "<p>Este es el calendario del curso.</p>"
    f'<p><img src="data:image/png;base64,{_PIXEL}" alt="Logotipo del colegio"></p>'
    "<ol><li>Inicio de curso, 8 de septiembre.</li>"
    "<li>Vacaciones de Navidad, del 23 de diciembre al 7 de enero.</li></ol>"
)
_CANTEEN_MENU: Final = (
    '<p>Consulte el menú de octubre en <a href="https://drive.google.com/file/d/ejemplo/view">'
    "este documento</a>.</p>"
)
_PARENTS_MEETING: Final = (
    "<p>Estimadas familias, la reunión será el 20 de septiembre a las 16:20.</p>"
)
_PARENTS_MEETING_IN_ENGLISH: Final = SimTranslation(
    "Parents' meeting",
    "<p>Dear families, the meeting will take place on 20 September at 16:20.</p>",
)


def _mail_of_marta() -> tuple[SimMessage, ...]:
    ana, carlos = "Ana Muestra Tutora", "Carlos Ejemplo Profesor"
    return (
        _received(
            0x1001,
            ana,
            "Reto de matemáticas",
            "2026-10-15 09:12",
            read=False,
            category="Aviso",
            body=_MATH_CHALLENGE,
            child_names="Lucía",
        ),
        _received(
            0x1002,
            "Secretaría",
            "  Excursión al museo  ",
            "2026-10-14 17:40",
            expires="2026-10-25",
            category="Encuesta",
            body=_MUSEUM_TRIP,
            files=(
                SimFile(
                    id=MUSEUM_FORM_FILE_ID,
                    name="Autorización museo.pdf",
                    data=_PDF,
                ),
            ),
            child_names="Lucía, Mateo",
            can_reply=False,
        ),
        _received(
            0x1003,
            carlos,
            "Horario de octubre",
            "2026-10-13 08:05",
            read=False,
            body=_OCTOBER_TIMETABLE,
            child_names="Lucía",
        ),
        _received(
            0x1004,
            ana,
            "Entrevista de tutoría",
            "2026-10-10 12:00",
            category="Entrevistas",
            body=_TUTORING_CALL,
            child_names="Lucía",
        ),
        _received(
            0x1005,
            "Dirección",
            "Calendario escolar",
            "2026-10-05 10:30",
            institutional=True,
            body=_SCHOOL_CALENDAR,
            child_names="Lucía, Mateo",
            can_reply=False,
        ),
        _received(
            0x1006,
            "Comedor",
            "Menú de octubre",
            "2026-09-30 11:00",
            anonymous=True,
            body=_CANTEEN_MENU,
            files=(
                SimFile(
                    id=f"{synthetic_guid(0xA02)}/menu-octubre.pdf",
                    name="Menú octubre.pdf",
                    data=_PDF,
                ),
            ),
            can_reply=False,
        ),
        _received(
            0x1007,
            ana,
            "Reunión de padres",
            "2026-09-20 16:20",
            body=_PARENTS_MEETING,
            child_names="Mateo",
            translations=(_PARENTS_MEETING_IN_ENGLISH,),
        ),
        _received(
            0x1008,
            "Dirección & Secretaría",
            "Bienvenida al curso",
            "2026-09-12 09:00",
            institutional=True,
            child_names="Lucía, Mateo",
            can_reply=False,
        ),
        _sent(0x2001, "Marta", "Ausencia de Lucía", "2026-10-01 20:15"),
        _sent(0x2002, "Marta", "Consulta sobre la excursión", "2026-09-15 18:00"),
    )


def _mail_of_pablo() -> tuple[SimMessage, ...]:
    return (
        _received(0x1101, "Rosa Prueba Tutora", "Bienvenida al curso", "2026-09-10 09:30"),
        _received(
            0x1102,
            "Tomás Demo Profesor",
            "Ensayo del coro",
            "2026-10-12 13:15",
            read=False,
            files=(
                SimFile(
                    id=f"{synthetic_guid(0xA11)}/partitura.pdf",
                    name="Partitura.pdf",
                    data=_PDF,
                ),
            ),
            child_names="Hugo",
        ),
        _received(0x1103, "Secretaría", "Recibo de octubre", "2026-10-02 10:00"),
        _sent(0x2101, "Pablo", "Cambio de autorización", "2026-10-03 19:45"),
    )


_BELLS: Final = (
    ("09:00", "09:45"),
    ("09:45", "10:30"),
    ("11:00", "11:45"),
    ("11:45", "12:30"),
    ("15:00", "15:45"),
    ("15:45", "16:30"),
)
_SUBJECTS: Final = (
    "Matemáticas",
    "Lengua",
    "Inglés",
    "Ciencias",
    "Educación Física",
    "Música",
    "Plástica",
    "Tutoría",
)
_TEACHERS: Final = (
    "Ana Muestra",
    "Carlos Ejemplo",
    "Rosa Prueba",
    "Tomás Demo",
    "Elena Modelo",
    "Iván Simulado",
)


def _timetable(owner: int) -> tuple[SimSlot, ...]:
    """Six lessons a day from Monday to Friday. Each pupil has another week, so a mix-up shows."""
    return tuple(
        SimSlot(
            id=synthetic_guid(0x7000 + owner * 0x100 + weekday * 0x10 + index),
            weekday=weekday,
            starts=starts,
            ends=ends,
            title=_SUBJECTS[(owner + weekday * 3 + index) % len(_SUBJECTS)],
            teacher=_TEACHERS[(owner + weekday + index) % len(_TEACHERS)],
        )
        for weekday in range(1, 6)
        for index, (starts, ends) in enumerate(_BELLS)
    )


def _occasion(
    number: int,
    title: str,
    first: tuple[int, int],
    last: tuple[int, int] | None = None,
    *,
    starts: str = "00:00",
    ends: str = "23:59",
) -> SimOccasion:
    return SimOccasion(
        id=synthetic_guid(number),
        title=title,
        first=first,
        last=last or first,
        starts=starts,
        ends=ends,
    )


def _school_calendar() -> tuple[SimOccasion, ...]:
    """The school's own dates. The portal writes a one-day holiday with either kind of end."""
    return (
        _occasion(0x7100, "FESTIVO", (10, 12), ends="00:00"),
        _occasion(0x7101, "FESTIVO", (12, 8)),
        _occasion(0x7102, "VACACIONES DE NAVIDAD", (12, 23), (1, 7)),
        _occasion(0x7103, "ESCUELA DE PASCUA", (3, 30), (4, 2), starts="09:00", ends="17:00"),
    )


def _absences_of_mateo() -> tuple[SimAbsence, ...]:
    """One open absence, two justified ones that differ in whether the school took them, a delay."""
    return (
        SimAbsence(
            synthetic_guid(0x7501),
            "2026-10-14",
            "Falta de asistencia",
            teacher="Rosa Prueba",
        ),
        SimAbsence(
            synthetic_guid(0x7502),
            "2026-10-13",
            "Falta de asistencia",
            teacher="Rosa Prueba",
            justified=True,
            justification="Enfermedad",
            accepted=True,
        ),
        SimAbsence(
            synthetic_guid(0x7503),
            "2026-10-12",
            "Falta de asistencia",
            teacher="Rosa Prueba",
            justified=True,
            justification="Cita médica",
        ),
        SimAbsence(
            synthetic_guid(0x7504),
            "2026-10-09",
            "Retraso",
            hour="09:05",
            area="Música",
            teacher="Tomás Demo",
            note="Llegó con el autobús siguiente.",
            justifiable=False,
        ),
    )


def _absences_of_alba() -> tuple[SimAbsence, ...]:
    return (
        SimAbsence(
            synthetic_guid(0x7511),
            "2026-10-15",
            "Falta de asistencia",
            teacher="Rosa Prueba",
        ),
        SimAbsence(
            synthetic_guid(0x7512),
            "2026-10-08",
            "Falta de asistencia",
            teacher="Rosa Prueba",
        ),
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
        guardian=SimGuardian(
            person_id=synthetic_guid(0x301),
            first_name="Marta",
            interviews=(
                _occasion(0x7301, "Entrevista: Aceptada", (10, 20), starts="16:00", ends="16:30"),
            ),
        ),
        children=(
            SimChild(
                student_id=synthetic_guid(0x101),
                person_id=synthetic_guid(0x201),
                full_name="Lucía Ejemplo Muestra",
                first_name="Lucía",
                relation="Hija",
                tracking=SimTracking(tasks=3, activities=1, notes=0, tests=2, incidents=0),
                staff=(tutor_a, maths),
                timetable=_timetable(1),
                events=(
                    _occasion(0x7211, "EXCURSIÓN AL MUSEO", (10, 30), starts="09:30", ends="14:00"),
                ),
            ),
            SimChild(
                student_id=synthetic_guid(0x102),
                person_id=synthetic_guid(0x202),
                full_name="Mateo Ejemplo Muestra",
                first_name="Mateo",
                relation="Hijo",
                tracking=SimTracking(tasks=1, activities=0, notes=2, tests=0, incidents=1),
                staff=(tutor_b, music),
                timetable=_timetable(2),
                events=(_occasion(0x7221, "SALIDA A LA GRANJA", (11, 6)),),
                absences=_absences_of_mateo(),
            ),
        ),
        messages=_mail_of_marta(),
    )
    family_b = SimFamily(
        username=DEMO_USER_B,
        password=DEMO_PASSWORD_B,
        guardian=SimGuardian(
            person_id=synthetic_guid(0x311),
            first_name="Pablo",
            interviews=(
                _occasion(0x7311, "Entrevista: Pendiente", (11, 10), starts="17:00", ends="17:30"),
            ),
        ),
        children=(
            SimChild(
                student_id=synthetic_guid(0x111),
                person_id=synthetic_guid(0x211),
                full_name="Hugo Prueba Demo",
                first_name="Hugo",
                relation="Hijo",
                tracking=SimTracking(tasks=5, activities=2, notes=1, tests=1, incidents=0),
                staff=(tutor_a, music),
                timetable=_timetable(3),
                events=(
                    _occasion(
                        0x7231, "ENSAYO GENERAL DEL CORO", (12, 15), starts="17:00", ends="18:30"
                    ),
                ),
            ),
            SimChild(
                student_id=synthetic_guid(0x112),
                person_id=synthetic_guid(0x212),
                full_name="Alba Prueba Demo",
                first_name="Alba",
                relation="Hija",
                tracking=SimTracking(tasks=0, activities=3, notes=0, tests=0, incidents=2),
                staff=(tutor_b, maths),
                timetable=_timetable(4),
                events=(_occasion(0x7241, "JORNADA DEPORTIVA", (11, 20)),),
                absences=_absences_of_alba(),
            ),
        ),
        messages=_mail_of_pablo(),
    )
    return SimWorld(
        institution_key=SIM_INSTITUTION_KEY,
        families=(family_a, family_b),
        calendar=_school_calendar(),
    )
