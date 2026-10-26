"""DynamoDB single-table access.

Key design (single athlete):
  PK=DAY  SK=YYYY-MM-DD                      daily wellness (sleep, HRV, readiness, RHR...)
  PK=ACT  SK=<start_local ISO>#<activityId>  one item per activity
  PK=META SK=sync | fitness                  last sync status, latest fitness snapshot
Range queries on SK give date windows without scans.
"""

import os
from datetime import date

from common.util import to_dynamo, to_plain

_TABLE = None


def table():
    global _TABLE
    if _TABLE is None:
        import boto3

        _TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    return _TABLE


def put_item(item: dict) -> None:
    table().put_item(Item=to_dynamo(item))


def put_items(items: list[dict]) -> None:
    if not items:
        return
    with table().batch_writer(overwrite_by_pkeys=["PK", "SK"]) as writer:
        for item in items:
            writer.put_item(Item=to_dynamo(item))


def get_item(pk: str, sk: str) -> dict | None:
    item = table().get_item(Key={"PK": pk, "SK": sk}).get("Item")
    return to_plain(item) if item else None


def query_range(pk: str, sk_start: str, sk_end: str) -> list[dict]:
    from boto3.dynamodb.conditions import Key

    kwargs = {"KeyConditionExpression": Key("PK").eq(pk) & Key("SK").between(sk_start, sk_end)}
    items: list[dict] = []
    while True:
        resp = table().query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return to_plain(items)
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def day_items(start: date, end: date) -> list[dict]:
    return query_range("DAY", start.isoformat(), end.isoformat())


def activity_items(start: date, end: date) -> list[dict]:
    # "~" sorts after digits and "T", so this captures every start time on the end date.
    return query_range("ACT", start.isoformat(), end.isoformat() + "~")
