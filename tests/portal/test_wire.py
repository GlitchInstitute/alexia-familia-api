"""The wire models name the portal's fields once and refuse anything that looks wrong."""

import json

import pytest
from pydantic import ValidationError

from alexia_api.portal import wire

GUID = "5afe0000-0000-4000-8000-000000000001"


def test_request_parameters_are_sent_under_the_portals_own_names() -> None:
    params = wire.ValidarRolParams(token="t", role_id=GUID, evaluate_multifactor=False)

    assert json.loads(params.model_dump_json(by_alias=True)) == {
        "token": "t",
        "idRol": GUID,
        "evaluarMultifactor": False,
    }


def test_request_parameters_refuse_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        wire.GetRolesParams(token="t", surprise="x")  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "build",
    [
        lambda: wire.TrackingParams(student_id="not-a-guid"),
        lambda: wire.RosterParams(student_id=GUID.upper() + "x"),
        lambda: wire.ValidarParams(token="", nickname="n", password="p"),
        lambda: wire.ValidarParams(token="t", nickname="", password="p"),
        lambda: wire.ValidarParams(token="t", nickname="n", password=""),
        lambda: wire.CheckSessionParams(counter=-1),
        lambda: wire.CheckSessionParams(counter="1"),  # type: ignore[arg-type]
        lambda: wire.FolderTreeParams(is_authorization="1"),  # type: ignore[arg-type]
        lambda: wire.SelectFolderParams(folder_id="IdCarpetaBorradores"),  # type: ignore[arg-type]
        lambda: wire.SelectFolderParams(folder_id="IdCarpetaRecibidos", search_text="x"),  # type: ignore[arg-type]
    ],
)
def test_request_parameters_refuse_bad_values(build: object) -> None:
    assert callable(build)
    with pytest.raises(ValidationError):
        build()


def test_request_models_are_frozen() -> None:
    params = wire.GetRolesParams(token="t")

    with pytest.raises(ValidationError):
        params.token = "other"  # type: ignore[misc]


def test_replies_use_the_portals_aliases_and_ignore_new_fields() -> None:
    reply = wire.GetRolesReply.model_validate(
        {"Error": None, "OK": [{"Identificador": GUID}], "multifactor": None, "Brand": "new"}
    )

    assert reply.roles is not None
    assert [role.identifier for role in reply.roles] == [GUID]
    assert reply.error is None


def test_replies_reject_a_wrong_type_instead_of_guessing() -> None:
    with pytest.raises(ValidationError):
        wire.CheckSessionReply.model_validate({"IsOk": "yes"})
    with pytest.raises(ValidationError):
        wire.CheckSessionReply.model_validate({"IsOk": 1})


def test_a_reply_missing_a_required_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        wire.TrackingReply.model_validate({"tareas": "", "actividades": ""})


def test_validar_rol_reply_carries_each_interstitial_marker() -> None:
    reply = wire.ValidarRolReply.model_validate(
        {"OKCuenta": False, "GuidCuenta": GUID, "CambiarPws": True, "muetraOpClassroom": "x"}
    )

    assert reply.account_confirmed is False
    assert reply.account_guid == GUID
    assert reply.change_password is True
    assert reply.show_classroom == "x"


def test_roster_items_use_the_portals_aliases() -> None:
    item = wire.RosterItem.model_validate({"Valor": GUID, "Texto": "Ana (Tutora)"})

    assert (item.value, item.text) == (GUID, "Ana (Tutora)")


def test_folder_requests_carry_the_values_the_portal_expects() -> None:
    tree = wire.FolderTreeParams()
    chosen = wire.SelectFolderParams(folder_id="IdCarpetaEnviados")

    assert json.loads(tree.model_dump_json(by_alias=True)) == {"IsAutorizacion": "0"}
    assert json.loads(chosen.model_dump_json(by_alias=True)) == {
        "idCarpeta": "IdCarpetaEnviados",
        "IsAutorizacion": "0",
        "TextoBusqueda": "",
    }


def test_the_folder_tree_reply_needs_only_the_tree() -> None:
    reply = wire.FolderTreeReply.model_validate({"nodos": "[]", "carpeta": "x", "other": 1})

    assert reply.nodes == "[]"
    with pytest.raises(ValidationError):
        wire.FolderTreeReply.model_validate({"carpeta": "IdCarpetaRecibidos"})


def test_guid_text_must_be_a_guid() -> None:
    with pytest.raises(ValidationError):
        wire.RoleChoice.model_validate({"Identificador": "123"})
