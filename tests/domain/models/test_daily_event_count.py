from datetime import date

from mergency.domain.models.daily_event_count import DailyEventCount


def test_daily_event_count_is_a_frozen_day_count_pair():
    bucket = DailyEventCount(day=date(2026, 9, 1), count=3)

    assert bucket.day == date(2026, 9, 1)
    assert bucket.count == 3
