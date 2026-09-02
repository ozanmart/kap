from __future__ import annotations

from kap.backends import IncrementalDisclosurePoller, JsonCheckpointStore
from kap.models.disclosure import Disclosure


def _disclosure(index: int) -> Disclosure:
    return Disclosure(disclosure_id=str(index), disclosure_index=index)


def test_incremental_poller_advances_json_checkpoint(tmp_path):
    rows = [_disclosure(10), _disclosure(12)]
    store = JsonCheckpointStore(tmp_path / "checkpoint.json")
    poller = IncrementalDisclosurePoller(lambda last: rows, store)

    assert [row.disclosure_index for row in poller.poll("bist")] == [10, 12]
    rows.append(_disclosure(15))
    assert [row.disclosure_index for row in poller.poll("bist")] == [15]
    assert store.load("bist") == 15
