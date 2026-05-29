import 'package:flutter/material.dart';

import '../data/credential_store.dart';
import '../theme/app_theme.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key, this.credentialStore = const TdxCredentialStore()});

  final TdxCredentialStore credentialStore;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _clientIdController = TextEditingController();
  final _clientSecretController = TextEditingController();
  var _source = TdxCredentialSource.none;
  var _loading = true;
  var _saving = false;
  var _secretVisible = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _clientIdController.dispose();
    _clientSecretController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('TDX'),
        actions: [IconButton(tooltip: '重新載入', onPressed: _loading ? null : _load, icon: const Icon(Icons.sync_rounded))],
      ),
      body: DecoratedBox(
        decoration: const BoxDecoration(gradient: AppGradients.softBrand),
        child: SafeArea(
          top: false,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
            children: [
              AnimatedSwitcher(
                duration: const Duration(milliseconds: 240),
                child: _loading ? const _SettingsSkeleton(key: ValueKey('loading')) : _CredentialPanel(key: const ValueKey('credentials'), source: _source, saving: _saving, clientIdController: _clientIdController, clientSecretController: _clientSecretController, secretVisible: _secretVisible, onToggleSecret: () => setState(() => _secretVisible = !_secretVisible), onSave: _save, onClear: _clear),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    final resolution = await widget.credentialStore.resolve();
    if (!mounted) return;
    _clientIdController.text = resolution.credentials?.clientId ?? '';
    _clientSecretController.text = resolution.credentials?.clientSecret ?? '';
    setState(() {
      _source = resolution.source;
      _loading = false;
    });
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    await widget.credentialStore.save(TdxCredentials(clientId: _clientIdController.text, clientSecret: _clientSecretController.text));
    if (!mounted) return;
    setState(() {
      _source = TdxCredentialSource.saved;
      _saving = false;
    });
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('TDX 已更新')));
  }

  Future<void> _clear() async {
    setState(() => _saving = true);
    await widget.credentialStore.clear();
    if (!mounted) return;
    setState(() => _saving = false);
    await _load();
  }
}

class _CredentialPanel extends StatelessWidget {
  const _CredentialPanel({super.key, required this.source, required this.saving, required this.clientIdController, required this.clientSecretController, required this.secretVisible, required this.onToggleSecret, required this.onSave, required this.onClear});

  final TdxCredentialSource source;
  final bool saving;
  final TextEditingController clientIdController;
  final TextEditingController clientSecretController;
  final bool secretVisible;
  final VoidCallback onToggleSecret;
  final VoidCallback onSave;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.92),
        borderRadius: BorderRadius.circular(8),
        boxShadow: [BoxShadow(color: AppColors.blue.withValues(alpha: 0.10), blurRadius: 28, offset: const Offset(0, 16))],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const _GradientIcon(icon: Icons.key_rounded),
              const SizedBox(width: 10),
              Expanded(child: _SourceChip(source: source)),
            ],
          ),
          const SizedBox(height: 18),
          TextField(
            controller: clientIdController,
            textInputAction: TextInputAction.next,
            decoration: const InputDecoration(labelText: 'Client ID', prefixIcon: Icon(Icons.badge_rounded)),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: clientSecretController,
            obscureText: !secretVisible,
            decoration: InputDecoration(
              labelText: 'Client Secret',
              prefixIcon: const Icon(Icons.lock_rounded),
              suffixIcon: IconButton(tooltip: secretVisible ? '隱藏' : '顯示', onPressed: onToggleSecret, icon: Icon(secretVisible ? Icons.visibility_off_rounded : Icons.visibility_rounded)),
            ),
          ),
          const SizedBox(height: 18),
          Row(
            children: [
              Expanded(
                child: FilledButton.icon(onPressed: saving ? null : onSave, icon: const Icon(Icons.save_rounded), label: const Text('儲存')),
              ),
              const SizedBox(width: 10),
              IconButton.filledTonal(tooltip: '清除', onPressed: saving ? null : onClear, icon: const Icon(Icons.delete_outline_rounded)),
            ],
          ),
        ],
      ),
    );
  }
}

class _SourceChip extends StatelessWidget {
  const _SourceChip({required this.source});

  final TdxCredentialSource source;

  @override
  Widget build(BuildContext context) {
    final (icon, label, color) = switch (source) {
      TdxCredentialSource.saved => (Icons.verified_rounded, '已儲存', AppColors.blue),
      TdxCredentialSource.defaults => (Icons.tune_rounded, '.env 預設', AppColors.rose),
      TdxCredentialSource.none => (Icons.error_outline_rounded, '待設定', AppColors.amber),
    };
    return Align(
      alignment: Alignment.centerLeft,
      child: DecoratedBox(
        decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(999)),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 16, color: color),
              const SizedBox(width: 6),
              Text(
                label,
                style: TextStyle(color: color, fontWeight: FontWeight.w900),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _GradientIcon extends StatelessWidget {
  const _GradientIcon({required this.icon});

  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 42,
      height: 42,
      decoration: BoxDecoration(gradient: AppGradients.brand, borderRadius: BorderRadius.circular(8)),
      child: Icon(icon, color: Colors.white),
    );
  }
}

class _SettingsSkeleton extends StatelessWidget {
  const _SettingsSkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 236,
      decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.84), borderRadius: BorderRadius.circular(8)),
      child: const Center(child: CircularProgressIndicator()),
    );
  }
}
