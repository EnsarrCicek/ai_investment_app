import 'collector_constants.dart';
import 'study_anchors.g.dart';

/// Europe/Istanbul has been a fixed UTC+03:00 (no DST) since 2016, so a constant offset is exact for every
/// session of this study; no timezone database is needed on the phone.
const Duration kIstanbulOffset = Duration(hours: 3);

/// Earliest background EOD run: 19:15 Istanbul (session closed + Yahoo delay margin).
const int kEodHour = 19;
const int kEodMinute = 15;

/// Same rule as the Windows collector: a response retrieved before 18:30 local may still be filling the
/// day's last bar.
const int kFinalAfterHour = 18;
const int kFinalAfterMinute = 30;

/// Wall-clock fields of an Istanbul local time, represented as a UTC DateTime (only y/m/d/h/m/s are used).
DateTime istanbulWallClock(DateTime instant) => instant.toUtc().add(kIstanbulOffset);

DateTime fromIstanbulWallClock(int y, int m, int d, [int hh = 0, int mm = 0]) =>
    DateTime.utc(y, m, d, hh, mm).subtract(kIstanbulOffset);

String _two(int v) => v.toString().padLeft(2, '0');

String isoDate(DateTime wall) => '${wall.year.toString().padLeft(4, '0')}-${_two(wall.month)}-${_two(wall.day)}';

String _clock(DateTime t) {
  final base = '${isoDate(t)}T${_two(t.hour)}:${_two(t.minute)}:${_two(t.second)}';
  final micros = t.millisecond * 1000 + t.microsecond;
  return micros == 0 ? base : '$base.${micros.toString().padLeft(6, '0')}';
}

/// Python `datetime.isoformat()` / pandas style: `2026-10-22T06:55:00+00:00` (microseconds only if non-zero).
String utcIso(DateTime instant) => '${_clock(instant.toUtc())}+00:00';

String utcIsoFromNs(int ns) => utcIso(DateTime.fromMicrosecondsSinceEpoch(ns ~/ 1000, isUtc: true));

String istanbulIso(DateTime instant) => '${_clock(istanbulWallClock(instant))}+03:00';

int toNs(DateTime instant) => instant.toUtc().microsecondsSinceEpoch * 1000;

/// Local (Istanbul) session date of an instant, `YYYY-MM-DD`.
String sessionDateOf(DateTime instant) => isoDate(istanbulWallClock(instant));

String sessionDateOfNs(int ns) => sessionDateOf(DateTime.fromMicrosecondsSinceEpoch(ns ~/ 1000, isUtc: true));

/// session_date < prospective start -> PRE_START_SHADOW, otherwise PROSPECTIVE_SHADOW. Both remain MOBILE_SHADOW.
String dataPhaseOf(String sessionDate) =>
    sessionDate.compareTo(kProspectiveStartSession) < 0 ? kPhasePreStart : kPhaseProspective;

/// Consumed-final days (postmortem only): never written to the shadow archive.
bool isConsumedFinalDay(String sessionDate) =>
    sessionDate.compareTo(kConsumedFinalFirstDay) >= 0 && sessionDate.compareTo(kConsumedFinalLastDay) <= 0;

bool _isWeekday(DateTime wall) => wall.weekday <= DateTime.friday;

/// Next weekday 19:15 Istanbul strictly after [now] (UTC instant).
DateTime nextEodSlot(DateTime now) {
  final wall = istanbulWallClock(now);
  var day = DateTime.utc(wall.year, wall.month, wall.day);
  for (var i = 0; i < 8; i++) {
    final candidate = fromIstanbulWallClock(day.year, day.month, day.day, kEodHour, kEodMinute);
    if (_isWeekday(day) && candidate.isAfter(now.toUtc())) return candidate;
    day = day.add(const Duration(days: 1));
  }
  throw StateError('no EOD slot found');
}

/// Partial (still forming) flags — same rule as the Windows collector (`storage.partial_flags`): the bar end is
/// after retrieval, or the bar is the response's last bar of the retrieval's local day while retrieval happened
/// before 18:30 local. Additionally a timestamp that is not on the interval grid (Yahoo's live row) is partial and
/// marks the grid bar it falls into as partial too.
List<bool> partialFlags(List<int> startsNs, String interval, DateTime retrievedAt) {
  final stepNs = kIntervalSeconds[interval]! * 1000000000;
  final retrievedNs = toNs(retrievedAt);
  final out = [for (final s in startsNs) s + stepNs > retrievedNs || s % stepNs != 0];
  if (startsNs.isEmpty) return out;
  final liveSlots = {for (final s in startsNs) if (s % stepNs != 0) s - s % stepNs};
  for (var i = 0; i < startsNs.length; i++) {
    if (liveSlots.contains(startsNs[i])) out[i] = true;
  }
  var last = 0;
  for (var i = 1; i < startsNs.length; i++) {
    if (startsNs[i] > startsNs[last]) last = i;
  }
  final localRetrieved = istanbulWallClock(retrievedAt);
  final beforeFinal = localRetrieved.hour < kFinalAfterHour ||
      (localRetrieved.hour == kFinalAfterHour && localRetrieved.minute < kFinalAfterMinute);
  if (sessionDateOfNs(startsNs[last]) == isoDate(localRetrieved) && beforeFinal) out[last] = true;
  return out;
}
