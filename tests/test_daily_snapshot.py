import json

from apps.snapshots.cli import run_snapshot
from apps.snapshots.growth import build_growth
from apps.snapshots.tiktok_profile import PublicAccessLimitedError


class FakeReader:
    def __init__(self, delay_seconds=0):
        self.delay_seconds = delay_seconds

    def close(self):
        pass

    def get_profile(self, handle):
        values = {"alpha": 1000, "beta": 2000}
        return {
            "handle": handle,
            "display_name": handle,
            "verified": False,
            "followers": values[handle],
            "following": 10,
            "total_likes": 100,
            "video_count": 20,
            "collected_at": "2026-10-02T10:00:00+00:00",
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


def test_not_found_is_terminal_for_same_day(tmp_path):
    public = tmp_path / "creators.json"
    _public(public)

    class OneMissingReader(FakeReader):
        def get_profile(self, handle):
            if handle == "beta":
                return None
            return super().get_profile(handle)

    result = run_snapshot(
        snapshot_day="2026-10-02",
        public_creators=public,
        snapshot_dir=tmp_path / "snapshots",
        state_file=tmp_path / "state.json",
        growth_file=tmp_path / "growth.json",
        reader_factory=OneMissingReader,
        delay_seconds=0,
    )

    assert result["status"] == "complete"
    assert result["processed_current_profiles"] == 2
    assert result["successful_current_profiles"] == 1
    assert result["unavailable_current_profiles"] == 1
    assert result["missing_current_profiles"] == 0


def test_same_day_rerun_skips_ok_and_not_found(tmp_path):
    public = tmp_path / "creators.json"
    _public(public)
    snapshot_dir = tmp_path / "snapshots"
    state_file = tmp_path / "state.json"
    growth_file = tmp_path / "growth.json"

    calls = []

    class CountingMissingReader(FakeReader):
        def get_profile(self, handle):
            calls.append(handle)
            if handle == "beta":
                return None
            return super().get_profile(handle)

    kwargs = dict(
        snapshot_day="2026-10-02",
        public_creators=public,
        snapshot_dir=snapshot_dir,
        state_file=state_file,
        growth_file=growth_file,
        reader_factory=CountingMissingReader,
        delay_seconds=0,
    )

    run_snapshot(**kwargs)
    assert calls == ["alpha", "beta"]

    calls.clear()
    run_snapshot(**kwargs)
    assert calls == []


def test_limited_profile_stays_retryable(tmp_path):
    public = tmp_path / "creators.json"
    _public(public)

    class LimitedReader(FakeReader):
        def get_profile(self, handle):
            if handle == "beta":
                raise PublicAccessLimitedError("WAF")
            return super().get_profile(handle)

    result = run_snapshot(
        snapshot_day="2026-10-02",
        public_creators=public,
        snapshot_dir=tmp_path / "snapshots",
        state_file=tmp_path / "state.json",
        growth_file=tmp_path / "growth.json",
        reader_factory=LimitedReader,
        delay_seconds=0,
    )

    assert result["status"] == "partial"
    assert result["successful_current_profiles"] == 1
    assert result["missing_current_profiles"] == 1
    assert result["stopped_by_rate_limit"] is True


def test_growth_ignores_partial_day(tmp_path):
    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir()

    # Partial Oct 1 must NOT become the baseline.
    (snap_dir / "2026-10-01.json").write_text(
        json.dumps(
            {
                "status": "partial",
                "creators": {
                    "alpha": {"followers": 1000, "rank": 10, "score": 60}
                },
            }
        ),
        encoding="utf-8",
    )

    (snap_dir / "2026-10-02.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "creators": {
                    "alpha": {"followers": 1100, "rank": 8, "score": 62}
                },
            }
        ),
        encoding="utf-8",
    )

    result = build_growth(snap_dir, tmp_path / "growth.json")
    row = result["creators"]["alpha"]

    assert result["available_snapshot_days"] == 1
    assert result["ignored_partial_snapshot_days"] == 1
    assert result["latest_date"] == "2026-10-02"
    assert row["followers_delta_1d"] is None
    assert row["followers_growth_1d_pct"] is None
    assert row["rank_change_1d"] is None


def test_growth_uses_only_complete_exact_day_baselines(tmp_path):
    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir()

    (snap_dir / "2026-10-02.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "creators": {
                    "alpha": {"followers": 1000, "rank": 10, "score": 60}
                },
            }
        ),
        encoding="utf-8",
    )
    (snap_dir / "2026-10-03.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "creators": {
                    "alpha": {"followers": 1100, "rank": 8, "score": 62}
                },
            }
        ),
        encoding="utf-8",
    )

    result = build_growth(snap_dir, tmp_path / "growth.json")
    row = result["creators"]["alpha"]

    assert row["followers_delta_1d"] == 100
    assert row["followers_growth_1d_pct"] == 10.0
    assert row["rank_change_1d"] == 2
    assert row["followers_delta_7d"] is None
    assert row["followers_delta_30d"] is None
    assert row["ath_rank"] == 8
