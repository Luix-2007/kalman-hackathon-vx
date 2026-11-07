import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from auth import user_id_from_event  # noqa: E402


def claims(c):
    return {"requestContext": {"authorizer": {"jwt": {"claims": c}}}}


def test_le_o_sub_do_token():
    assert user_id_from_event(claims({"sub": "abc-123", "email": "a@b.com"})) == "abc-123"


@pytest.mark.parametrize("event", [
    {},
    {"requestContext": None},
    {"requestContext": {}},
    {"requestContext": {"authorizer": {}}},
    claims({}),
    claims({"sub": ""}),
    claims({"sub": "   "}),
])
def test_sem_token_retorna_none(event):
    assert user_id_from_event(event) is None


def test_ignora_user_id_fora_do_token():
    event = {"body": '{"user_id": "hacker"}', "pathParameters": {"user_id": "hacker"}}
    assert user_id_from_event(event) is None
