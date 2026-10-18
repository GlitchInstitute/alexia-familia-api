"""The registry gives each account its own gateway and cache, and finds children through them."""

from dataclasses import replace
from datetime import timedelta

import pytest

from alexia_api.clock import ManualClock
from alexia_api.config import CacheTtls, ConfigError
from alexia_api.domain.accounts import Blocked, Capabilities, LoggedIn, LoggedOut
from alexia_api.domain.children import TrackingCounters
from alexia_api.domain.errors import BreakerOpen, InvalidCredentials
from alexia_api.domain.ids import parse_account_id
from alexia_api.domain.security import Principal
from alexia_api.portal.breaker import BreakerStore
from alexia_api.portal.inbox import Feed
from alexia_api.services.errors import NotFoundError
from alexia_api.services.registry import Directory, Registry
from alexia_api.sim.world import DEMO_PASSWORD_B, DEMO_USER_B, default_world, synthetic_guid
from tests.harness import Failure, Harness

LUCIA = synthetic_guid(0x101)
MATEO = synthetic_guid(0x102)
HUGO = synthetic_guid(0x111)


async def test_accounts_are_kept_in_the_order_they_were_configured(harness: Harness) -> None:
    registry = harness.registry()

    assert [runtime.account for runtime in registry.accounts] == ["marta", "pablo"]


@pytest.mark.parametrize("name", ["nobody", "Marta Family", "../etc", ""])
async def test_an_account_that_is_not_held_is_not_found(harness: Harness, name: str) -> None:
    registry = harness.registry()

    with pytest.raises(NotFoundError) as raised:
        registry.get(name)

    assert (raised.value.kind, raised.value.reference) == ("account", name)


async def test_the_directory_names_the_guardian_and_gives_each_child_a_slug(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")

    directory = (await runtime.directory()).value

    assert directory.guardian is not None
    assert directory.guardian.first_name == "Marta"
    assert [(child.id, child.slug) for child in directory.children] == [
        (LUCIA, "lucia"),
        (MATEO, "mateo"),
    ]


async def test_each_account_sees_only_the_children_the_portal_lists_for_it(
    harness: Harness,
) -> None:
    registry = harness.registry()

    marta = (await registry.get("marta").directory()).value
    pablo = (await registry.get("pablo").directory()).value

    assert [child.slug for child in marta.children] == ["lucia", "mateo"]
    assert [child.slug for child in pablo.children] == ["hugo", "alba"]


async def test_a_second_look_at_the_directory_does_not_call_the_portal(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    first = await runtime.directory()
    calls = len(harness.sim.requests)

    second = await runtime.directory()

    assert (first.status, second.status) == ("miss", "hit")
    assert len(harness.sim.requests) == calls


async def test_a_fresh_look_reads_the_portal_again_but_keeps_the_session(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")
    await runtime.directory()
    calls = len(harness.sim.requests)

    again = await runtime.directory(fresh=True)

    assert again.status == "bypass"
    assert len(harness.sim.requests) > calls
    assert harness.requests_to("/Validar") == 1


async def test_the_directory_is_read_again_once_its_time_to_live_is_up(
    harness: Harness, clock: ManualClock
) -> None:
    runtime = harness.registry().get("marta")
    await runtime.directory()

    clock.advance(899)
    assert (await runtime.directory()).status == "hit"
    clock.advance(2)

    assert (await runtime.directory()).status == "miss"
    assert harness.requests_to("/Validar") == 1


async def test_a_child_is_found_by_slug_or_by_student_id_in_any_case(harness: Harness) -> None:
    runtime = harness.registry().get("marta")

    by_slug = (await runtime.child("lucia")).value
    by_id = (await runtime.child(LUCIA.upper())).value

    assert by_slug == by_id
    assert by_slug.first_name == "Lucía"


@pytest.mark.parametrize("reference", ["hugo", HUGO, "nobody", ""])
async def test_a_child_the_account_does_not_list_is_not_found(
    harness: Harness, reference: str
) -> None:
    runtime = harness.registry().get("marta")

    with pytest.raises(NotFoundError) as raised:
        await runtime.child(reference)

    assert (raised.value.kind, raised.value.reference) == ("child", reference)


async def test_a_missing_child_is_decided_from_the_cache_without_calling_the_portal(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")
    await runtime.directory()
    calls = len(harness.sim.requests)

    with pytest.raises(NotFoundError):
        await runtime.child("nobody")

    assert len(harness.sim.requests) == calls


async def test_a_child_lookup_reports_how_its_directory_was_found(harness: Harness) -> None:
    runtime = harness.registry().get("marta")

    first = await runtime.child("lucia")
    second = await runtime.child("mateo")
    third = await runtime.child("mateo", fresh=True)

    assert (first.status, second.status, third.status) == ("miss", "hit", "bypass")


async def test_pinned_slugs_win_over_the_ones_derived_from_names(harness: Harness) -> None:
    settings = harness.settings(
        accounts={"marta": harness.account_settings(slugs={"first-born": LUCIA})}
    )
    runtime = harness.registry(settings).get("marta")

    directory = (await runtime.directory()).value

    assert [child.slug for child in directory.children] == ["first-born", "mateo"]
    assert (await runtime.child("first-born")).value.id == LUCIA
    with pytest.raises(NotFoundError):
        await runtime.child("lucia")


async def test_tracking_is_read_for_the_child_asked_about(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value
    mateo = (await runtime.child("mateo")).value

    assert (await runtime.tracking(lucia)).value == TrackingCounters(
        tasks=3, activities=1, notes=0, tests=2, incidents=0
    )
    assert (await runtime.tracking(mateo)).value == TrackingCounters(
        tasks=1, activities=0, notes=2, tests=0, incidents=1
    )


async def test_tracking_is_cached_for_each_child_on_its_own(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value
    mateo = (await runtime.child("mateo")).value
    await runtime.tracking(lucia)
    calls = len(harness.sim.requests)

    again = await runtime.tracking(lucia)
    other = await runtime.tracking(mateo)

    assert (again.status, other.status) == ("hit", "miss")
    assert len(harness.sim.requests) == calls + 1


async def test_a_time_to_live_of_zero_turns_the_cache_off(harness: Harness) -> None:
    settings = harness.settings(cache=CacheTtls(tracking=0))
    runtime = harness.registry(settings).get("marta")
    lucia = (await runtime.child("lucia")).value

    first = await runtime.tracking(lucia)
    second = await runtime.tracking(lucia)

    assert (first.status, second.status) == ("miss", "miss")


async def test_staff_comes_from_the_roster_of_that_child(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value
    mateo = (await runtime.child("mateo")).value

    lucia_staff = (await runtime.staff(lucia)).value
    mateo_staff = (await runtime.staff(mateo)).value

    assert [(member.id, member.role) for member in lucia_staff] == [
        (synthetic_guid(0x601), "Tutora"),
        (synthetic_guid(0x602), "Matemáticas"),
    ]
    assert [(member.id, member.role) for member in mateo_staff] == [
        (synthetic_guid(0x603), "Tutora"),
        (synthetic_guid(0x604), "Música"),
    ]


async def test_staff_is_cached_for_longer_than_tracking(
    harness: Harness, clock: ManualClock
) -> None:
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value
    await runtime.tracking(lucia)
    await runtime.staff(lucia)

    clock.advance(300)

    assert (await runtime.tracking(lucia)).status == "miss"
    assert (await runtime.staff(lucia)).status == "hit"


@pytest.mark.parametrize(("name", "received", "sent"), [("marta", 8, 2), ("pablo", 3, 1)])
async def test_each_account_lists_the_folders_of_its_own_mailbox(
    harness: Harness, name: str, received: int, sent: int
) -> None:
    folders = (await harness.registry().get(name).folders()).value

    assert [(folder.name, folder.count) for folder in folders] == [
        ("received", received),
        ("sent", sent),
    ]


async def test_the_folders_are_kept_for_five_minutes(harness: Harness, clock: ManualClock) -> None:
    runtime = harness.registry().get("marta")
    first = await runtime.folders()
    calls = len(harness.sim.requests)

    clock.advance(299)
    second = await runtime.folders()
    assert len(harness.sim.requests) == calls
    clock.advance(2)
    third = await runtime.folders()

    assert (first.status, second.status, third.status) == ("miss", "hit", "miss")


async def test_a_fresh_look_at_the_folders_reads_the_portal_again(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    await runtime.folders()
    calls = len(harness.sim.requests)

    again = await runtime.folders(fresh=True)

    assert again.status == "bypass"
    assert len(harness.sim.requests) > calls


async def test_the_messages_of_each_folder_and_each_account_are_kept_apart(
    harness: Harness,
) -> None:
    registry = harness.registry()
    marta = registry.get("marta")

    received = await marta.messages("received")
    sent = await marta.messages("sent")
    pablo = await registry.get("pablo").messages("received")

    received_ids, sent_ids, pablo_ids = (
        {message.id for message in listing.value.messages} for listing in (received, sent, pablo)
    )
    assert (len(received_ids), len(sent_ids), len(pablo_ids)) == (8, 2, 3)
    assert received_ids.isdisjoint(sent_ids)
    assert received_ids.isdisjoint(pablo_ids)
    assert [listing.status for listing in (received, sent, pablo)] == ["miss", "miss", "miss"]


async def test_every_kind_of_answer_is_kept_under_a_key_of_its_own(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value

    async def everything() -> list[object]:
        return [
            (await runtime.directory()).value,
            (await runtime.folders()).value,
            (await runtime.messages("received")).value,
            (await runtime.messages("sent")).value,
            (await runtime.tracking(lucia)).value,
            (await runtime.staff(lucia)).value,
        ]

    first = await everything()
    again = await everything()

    assert [type(answer) for answer in first] == [
        Directory,
        tuple,
        Feed,
        Feed,
        TrackingCounters,
        tuple,
    ]
    assert again == first


async def test_a_message_list_is_read_once_however_often_it_is_asked_for(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")
    first = await runtime.messages("received")
    calls = len(harness.sim.requests)

    second = await runtime.messages("received")

    assert (first.status, second.status) == ("miss", "hit")
    assert second.value == first.value
    assert len(harness.sim.requests) == calls


async def test_a_message_list_is_read_again_after_two_minutes(
    harness: Harness, clock: ManualClock
) -> None:
    runtime = harness.registry().get("marta")
    await runtime.messages("received")

    clock.advance(119)
    assert (await runtime.messages("received")).status == "hit"
    clock.advance(2)

    assert (await runtime.messages("received")).status == "miss"


async def test_a_fresh_look_sees_a_message_that_arrived_since(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    before = await runtime.messages("received")
    arrived = replace(
        default_world().families[0].messages[0],
        guid=synthetic_guid(0x1100),
        subject="Nuevo aviso",
        date="2026-10-17",
        read=False,
    )
    harness.deliver("marta.ejemplo", arrived)

    stale = await runtime.messages("received")
    fresh = await runtime.messages("received", fresh=True)

    assert stale.value == before.value
    assert fresh.status == "bypass"
    assert len(fresh.value.messages) == len(before.value.messages) + 1
    assert fresh.value.messages[0].subject == "Nuevo aviso"


async def test_a_blocked_account_does_not_stop_the_other_account(
    harness: Harness, failure: Failure
) -> None:
    settings = harness.settings(
        accounts={
            "marta": harness.account_settings(password="not-her-password"),
            "pablo": harness.account_settings(DEMO_USER_B, DEMO_PASSWORD_B),
        }
    )
    registry = harness.registry(settings)

    first = await failure(registry.get("marta").directory())
    second = await failure(registry.get("marta").directory())
    pablo = await registry.get("pablo").directory()

    assert isinstance(first, InvalidCredentials)
    assert isinstance(second, BreakerOpen)
    assert [child.slug for child in pablo.value.children] == ["hugo", "alba"]
    assert harness.requests_to("/Validar") == 2
    assert isinstance((await registry.get("marta").status()).connection, Blocked)
    assert isinstance((await registry.get("pablo").status()).connection, LoggedIn)


async def test_a_block_is_kept_in_the_state_directory_under_the_account_name(
    harness: Harness, failure: Failure
) -> None:
    settings = harness.settings(
        accounts={"marta": harness.account_settings(password="not-her-password")}
    )
    await failure(harness.registry(settings).get("marta").directory())

    assert (harness.state_dir / "breaker" / "marta.json").is_file()


async def test_a_block_left_by_an_earlier_run_is_respected_at_startup(
    harness: Harness, clock: ManualClock, failure: Failure
) -> None:
    settings = harness.settings(
        accounts={"marta": harness.account_settings(password="not-her-password")}
    )
    await failure(harness.registry(settings).get("marta").directory())
    logins = harness.requests_to("/Validar")

    restarted = harness.registry(settings)
    detail = await failure(restarted.get("marta").directory())

    assert isinstance(detail, BreakerOpen)
    assert harness.requests_to("/Validar") == logins
    assert isinstance((await restarted.get("marta").status()).connection, Blocked)
    assert BreakerStore(harness.state_dir / "breaker", clock).read(parse_account_id("marta"))


async def test_resetting_a_block_lets_the_next_request_try_the_portal_again(
    harness: Harness, failure: Failure
) -> None:
    settings = harness.settings(
        accounts={"marta": harness.account_settings(password="not-her-password")}
    )
    runtime = harness.registry(settings).get("marta")
    await failure(runtime.directory())

    assert await runtime.reset_block() is True
    assert await runtime.reset_block() is False
    detail = await failure(runtime.directory())

    assert isinstance(detail, InvalidCredentials)
    assert harness.requests_to("/Validar") == 2


async def test_status_describes_the_account_without_calling_the_portal(harness: Harness) -> None:
    settings = harness.settings(
        accounts={"marta": harness.account_settings(label="Marta's account")}
    )
    runtime = harness.registry(settings).get("marta")

    before = await runtime.status()

    assert isinstance(before.connection, LoggedOut)
    assert before.child_count is None
    assert before.id == "marta"
    assert before.label == "Marta's account"
    assert before.portal_host == "sim.invalid"
    assert before.capabilities == Capabilities(writes=False, forms=False, restore_unread=False)
    assert harness.sim.requests == []


async def test_status_after_a_login_shows_the_session_and_the_children_seen(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")
    await runtime.directory()
    calls = len(harness.sim.requests)

    after = await runtime.status()

    assert isinstance(after.connection, LoggedIn)
    assert after.child_count == 2
    assert after.label == "marta"
    assert len(harness.sim.requests) == calls


@pytest.mark.parametrize(("zone", "hours"), [("Europe/Madrid", 1), ("Asia/Tokyo", 9)])
async def test_times_the_server_makes_carry_the_offset_of_the_school_zone(
    harness: Harness, zone: str, hours: int
) -> None:
    runtime = harness.registry(harness.settings(timezone=zone)).get("marta")
    await runtime.directory()

    connection = (await runtime.status()).connection

    assert isinstance(connection, LoggedIn)
    assert connection.since.utcoffset() == timedelta(hours=hours)
    assert connection.last_success_at.utcoffset() == timedelta(hours=hours)


async def test_the_operator_switches_show_in_the_status(harness: Harness) -> None:
    settings = harness.settings(allow_writes=True, allow_forms=True, restore_unread=True)

    status = await harness.registry(settings).get("marta").status()

    assert status.capabilities == Capabilities(writes=True, forms=True, restore_unread=True)


async def test_a_check_logs_in_and_says_whether_the_session_was_new(harness: Harness) -> None:
    runtime = harness.registry().get("marta")

    first = await runtime.check()
    second = await runtime.check()

    assert (first.session, first.child_count) == ("new", 2)
    assert second.session == "reused"


async def test_secrets_can_be_read_from_the_environment(harness: Harness) -> None:
    settings = harness.settings(
        accounts={
            "marta": harness.account_settings("env:MARTA_USER", "env:MARTA_PASSWORD"),
        }
    )
    registry = harness.registry(
        settings,
        environ={"MARTA_USER": "marta.ejemplo", "MARTA_PASSWORD": "demo-password-a"},
    )

    directory = (await registry.get("marta").directory()).value

    assert [child.slug for child in directory.children] == ["lucia", "mateo"]


async def test_a_secret_that_is_not_set_stops_the_build_before_anything_connects(
    harness: Harness,
) -> None:
    settings = harness.settings(
        accounts={
            "marta": harness.account_settings(),
            "pablo": harness.account_settings(DEMO_USER_B, "env:PABLO_PASSWORD"),
        }
    )

    with pytest.raises(ConfigError, match=r"accounts\.pablo\.password.*PABLO_PASSWORD"):
        Registry.build(settings, environ={}, clock=harness.clock)

    assert harness.sim.requests == []


async def test_only_the_accounts_a_key_may_use_are_visible_to_it(harness: Harness) -> None:
    registry = harness.registry()
    only_pablo = Principal(
        key_name="pablo-only", scopes=frozenset({"read"}), accounts=frozenset({"pablo"})
    )
    everything = Principal(
        key_name="everything", scopes=frozenset({"read"}), accounts=frozenset({"*"})
    )

    assert [runtime.account for runtime in registry.visible_to(only_pablo)] == ["pablo"]
    assert [runtime.account for runtime in registry.visible_to(everything)] == ["marta", "pablo"]


async def test_closing_the_registry_twice_is_harmless(harness: Harness) -> None:
    registry = harness.registry()

    await registry.aclose()
    await registry.aclose()
