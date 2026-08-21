class IpoListing {
  final String companyName;
  final String? bistCode;
  final String detailUrl;
  final String dateText;
  final String? badgeText;

  IpoListing({
    required this.companyName,
    required this.bistCode,
    required this.detailUrl,
    required this.dateText,
    required this.badgeText,
  });

  factory IpoListing.fromJson(Map<String, dynamic> json) {
    return IpoListing(
      companyName: json['company_name'] as String,
      bistCode: json['bist_code'] as String?,
      detailUrl: json['detail_url'] as String,
      dateText: json['date_text'] as String? ?? '',
      badgeText: json['badge_text'] as String?,
    );
  }
}

class IpoDetail {
  final String companyName;
  final String? bistCode;
  final Map<String, String> fields;
  final List<Map<String, String>> demandResults;
  final DateTime fetchedAt;

  IpoDetail({
    required this.companyName,
    required this.bistCode,
    required this.fields,
    required this.demandResults,
    required this.fetchedAt,
  });

  factory IpoDetail.fromJson(Map<String, dynamic> json) {
    return IpoDetail(
      companyName: json['company_name'] as String,
      bistCode: json['bist_code'] as String?,
      fields: (json['fields'] as Map<String, dynamic>? ?? {}).map((k, v) => MapEntry(k, v as String)),
      demandResults: (json['demand_results'] as List<dynamic>? ?? [])
          .map((e) => (e as Map<String, dynamic>).map((k, v) => MapEntry(k, v as String)))
          .toList(),
      fetchedAt: DateTime.parse(json['fetched_at'] as String),
    );
  }
}

class IpoNote {
  final String? id;
  final String companyName;
  final String? bistCode;
  final String noteText;
  final DateTime createdAt;

  IpoNote({
    required this.id,
    required this.companyName,
    required this.bistCode,
    required this.noteText,
    required this.createdAt,
  });

  factory IpoNote.fromJson(Map<String, dynamic> json) {
    return IpoNote(
      id: json['id'] as String?,
      companyName: json['company_name'] as String,
      bistCode: json['bist_code'] as String?,
      noteText: json['note_text'] as String,
      createdAt: DateTime.parse(json['created_at'] as String),
    );
  }
}
