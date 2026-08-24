import 'package:flutter/material.dart';

import '../../widgets/gradient_app_bar.dart';

import '../../models/ipo.dart';
import '../../models/news_item.dart';
import '../../services/api/ipo_api.dart';
import '../../utils/url_launch.dart';

class IpoDetailScreen extends StatefulWidget {
  final IpoListing listing;
  const IpoDetailScreen({super.key, required this.listing});

  @override
  State<IpoDetailScreen> createState() => _IpoDetailScreenState();
}

class _IpoDetailScreenState extends State<IpoDetailScreen> {
  late Future<IpoDetail> _detailFuture;
  late Future<List<NewsItem>> _newsFuture;
  late Future<List<IpoNote>> _notesFuture;
  final _noteController = TextEditingController();
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _detailFuture = IpoApi().fetchDetail(widget.listing.detailUrl);
    _newsFuture = IpoApi().fetchNews(widget.listing.companyName);
    _notesFuture = IpoApi().fetchNotes(companyName: widget.listing.companyName);
  }

  @override
  void dispose() {
    _noteController.dispose();
    super.dispose();
  }

  Future<void> _saveNote() async {
    final text = _noteController.text.trim();
    if (text.isEmpty) return;
    setState(() => _saving = true);
    try {
      await IpoApi().createNote(
        companyName: widget.listing.companyName,
        bistCode: widget.listing.bistCode,
        noteText: text,
      );
      _noteController.clear();
      setState(() {
        _notesFuture = IpoApi().fetchNotes(companyName: widget.listing.companyName);
      });
      await _notesFuture;
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Not kaydedilemedi: $e')));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _deleteNote(IpoNote note) async {
    if (note.id == null) return;
    try {
      await IpoApi().deleteNote(note.id!);
      setState(() {
        _notesFuture = IpoApi().fetchNotes(companyName: widget.listing.companyName);
      });
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Silinemedi: $e')));
      }
    }
  }

  static String _fmtDate(DateTime date) {
    final local = date.toLocal();
    final day = local.day.toString().padLeft(2, '0');
    final month = local.month.toString().padLeft(2, '0');
    final hour = local.hour.toString().padLeft(2, '0');
    final minute = local.minute.toString().padLeft(2, '0');
    return '$day.$month.${local.year} $hour:$minute';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: GradientAppBar(title: Text(widget.listing.companyName, overflow: TextOverflow.ellipsis)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          FutureBuilder<IpoDetail>(
            future: _detailFuture,
            builder: (context, snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const Padding(
                  padding: EdgeInsets.symmetric(vertical: 24),
                  child: Center(child: CircularProgressIndicator()),
                );
              }
              if (snapshot.hasError) {
                return Text('Detay alınamadı: ${snapshot.error}', style: const TextStyle(color: Colors.red));
              }
              final detail = snapshot.data!;
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _SectionCard(
                    title: 'Halka Arz Bilgileri',
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: detail.fields.entries
                          .map(
                            (e) => Padding(
                              padding: const EdgeInsets.symmetric(vertical: 4),
                              child: Row(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  SizedBox(
                                    width: 150,
                                    child: Text(e.key, style: const TextStyle(color: Colors.grey, fontSize: 12)),
                                  ),
                                  Expanded(
                                    child: Text(
                                      e.value,
                                      style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          )
                          .toList(),
                    ),
                  ),
                  if (detail.demandResults.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    _SectionCard(
                      title: 'Talep Sonuçları',
                      child: Column(
                        children: [
                          const Row(
                            children: [
                              Expanded(
                                flex: 2,
                                child: Text('Grup', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 11)),
                              ),
                              Expanded(
                                child: Text('Kişi', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 11)),
                              ),
                              Expanded(
                                child: Text('Oran', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 11)),
                              ),
                            ],
                          ),
                          const Divider(),
                          ...detail.demandResults.map(
                            (r) => Padding(
                              padding: const EdgeInsets.symmetric(vertical: 3),
                              child: Row(
                                children: [
                                  Expanded(
                                    flex: 2,
                                    child: Text(r['grup'] ?? '', style: const TextStyle(fontSize: 12)),
                                  ),
                                  Expanded(child: Text(r['kisi'] ?? '', style: const TextStyle(fontSize: 12))),
                                  Expanded(
                                    child: Text(
                                      r['oran'] ?? '',
                                      style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ],
              );
            },
          ),
          const SizedBox(height: 16),
          const Text('Haberler', style: TextStyle(fontWeight: FontWeight.bold)),
          const SizedBox(height: 4),
          const Text(
            'Bu halka arzla ilgili gerçek haber kaynaklarında bulunanlar — araştırmanıza yardımcı olması için.',
            style: TextStyle(fontSize: 11, color: Colors.grey),
          ),
          const SizedBox(height: 8),
          FutureBuilder<List<NewsItem>>(
            future: _newsFuture,
            builder: (context, snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const Padding(
                  padding: EdgeInsets.symmetric(vertical: 12),
                  child: Center(child: CircularProgressIndicator()),
                );
              }
              if (snapshot.hasError) {
                return Text('Haberler alınamadı: ${snapshot.error}', style: const TextStyle(fontSize: 12));
              }
              final items = snapshot.data!;
              if (items.isEmpty) {
                return const Text('Haber bulunamadı.', style: TextStyle(color: Colors.grey, fontSize: 12));
              }
              return Column(
                children: items
                    .map(
                      (n) => Card(
                        margin: const EdgeInsets.only(bottom: 6),
                        child: ListTile(
                          dense: true,
                          title: Text(n.title, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.bold)),
                          subtitle: Text(n.publisher, style: const TextStyle(fontSize: 11, color: Colors.grey)),
                          onTap: () => openExternalUrl(context, n.url),
                        ),
                      ),
                    )
                    .toList(),
              );
            },
          ),
          const SizedBox(height: 16),
          const Text('Notlarım', style: TextStyle(fontWeight: FontWeight.bold)),
          const SizedBox(height: 4),
          const Text(
            'Kendi gözlemlerinizi yazın (ör. "şu an bu kadar alış bu kadar satış var, bence '
            'satmalıyım") — kalıcı olarak saklanır, AI tarafından üretilmez.',
            style: TextStyle(fontSize: 11, color: Colors.grey),
          ),
          const SizedBox(height: 8),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: TextField(
                  controller: _noteController,
                  minLines: 2,
                  maxLines: 4,
                  decoration: const InputDecoration(border: OutlineInputBorder(), hintText: 'Notunuzu yazın...'),
                ),
              ),
              const SizedBox(width: 8),
              IconButton(
                onPressed: _saving ? null : _saveNote,
                icon: _saving
                    ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.send),
              ),
            ],
          ),
          const SizedBox(height: 12),
          FutureBuilder<List<IpoNote>>(
            future: _notesFuture,
            builder: (context, snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const SizedBox.shrink();
              }
              if (snapshot.hasError) {
                return Text('Notlar alınamadı: ${snapshot.error}', style: const TextStyle(fontSize: 12));
              }
              final notes = snapshot.data ?? const <IpoNote>[];
              if (notes.isEmpty) {
                return const Text('Henüz not eklenmedi.', style: TextStyle(color: Colors.grey, fontSize: 12));
              }
              return Column(
                children: notes
                    .map(
                      (note) => Card(
                        margin: const EdgeInsets.only(bottom: 6),
                        child: ListTile(
                          title: Text(note.noteText, style: const TextStyle(fontSize: 13)),
                          subtitle: Text(_fmtDate(note.createdAt), style: const TextStyle(fontSize: 11, color: Colors.grey)),
                          trailing: IconButton(
                            icon: const Icon(Icons.delete_outline, size: 20),
                            onPressed: () => _deleteNote(note),
                          ),
                        ),
                      ),
                    )
                    .toList(),
              );
            },
          ),
        ],
      ),
    );
  }
}

class _SectionCard extends StatelessWidget {
  final String title;
  final Widget child;
  const _SectionCard({required this.title, required this.child});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            child,
          ],
        ),
      ),
    );
  }
}
