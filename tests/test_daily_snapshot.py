import json
from pathlib import Path

from apps.snapshots.cli import run_snapshot
from apps.snapshots.growth import build_growth


class FakeReader:
    def __init__(self, delay_seconds=0):
        self.delay_seconds = delay_seconds

    def close(self):
        pass

    def get_profile(self, handle):
        values = {
            "alpha": 1000,
            "beta": 2000,
        }
        return {
            "handle": handle,
            "display_name": handle,
            "verified": False,
            "followers": values[handle],
            "following": 10,
            "total_likes": 100,
            "video_count": 20,
            "collected_at": "2026-10-01T10:00:00+00:00",
        }


def _public(path):
    path.write_text(
        json.dumps(
            {
                "creators": [
                    {
                        "handle": "alpha",
                        "name": "Alpha",
                        "rank": 1,
                        "score": 90,
                        "category": "Tech",
                        "city": "Warszawa",
                    },
                    {
                        "handle": "beta",
                        "name": "Beta",
                        "rank": 2,
                        "score": 80,
                        "category": "Food",
                        "city": None,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )


def test_snapshot_writes_profile_and_rank_history(tmp_path):
    public = tmp_path / "creators.json"
    _public(public)

    snapshot_dir = tmp_path / "snapshots"
    state = tmp_path / "state.json"
    growth = tmp_path / "growth.json"

    result = run_snapshot(
        snapshot_day="2026-10-01",
        max_profiles=0,
        delay_seconds=0,
        public_creators=public,
        snapshot_dir=snapshot_dir,
        state_file=state,
        growth_file=growth,
        reader_factory=FakeReader,
    )

    assert result["status"] == "complete"
    assert result["creators"]["alpha"]["followers"] == 1000
    assert result["creators"]["alpha"]["rank"] == 1
    assert result["creators"]["alpha"]["city"] == "Warszawa"


def test_same_day_rerun_skips_successful_profiles(tmp_path):
    public = tmp_path / "creators.json"
    _public(public)
    snapshot_dir = tmp_path / "snapshots"
    state = tmp_path / "state.json"
    growth = tmp_path / "growth.json"

    calls = []

    class CountingReader(FakeReader):
        def get_profile(self, handle):
            calls.append(handle)
            return super().get_profile(handle)

    kwargs = dict(
        snapshot_day="2026-10-01",
        max_profiles=0,
        delay_seconds=0,
        public_creators=public,
        snapshot_dir=snapshot_dir,
        state_file=state,
        growth_file=growth,
        reader_factory=CountingReader,
    )

    run_snapshot(**kwargs)
    assert calls == ["alpha", "beta"]

    calls.clear()
    run_snapshot(**kwargs)
    assert calls == []


def test_growth_uses_exact_daily_snapshots(tmp_path):
    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir()

    (snap_dir / "2026-10-01.json").write_text(
        json.dumps(
            {
                "creators": {
                    "alpha": {"followers": 1000, "rank": 10, "score": 60}
                }
            }
        ),
        encoding="utf-8",
    )
    (snap_dir / "2026-10-02.json").write_text(
        json.dumps(
            {
                "creators": {
                    "alpha": {"followers": 1100, "rank": 8, "score": 62}
                }
            }
        ),
        encoding="utf-8",
    )

    output = tmp_path / "growth.json"
    result = build_growth(snap_dir, output)

    row = result["creators"]["alpha"]
    assert row["followers_delta_1d"] == 100
    assert row["followers_growth_1d_pct"] == 10.0
    assert row["rank_change_1d"] == 2
    assert row["followers_delta_7d"] is None
    assert row["ath_rank"] == 8
