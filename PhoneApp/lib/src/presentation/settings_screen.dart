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
      backgroundColor: AppColors.surface,
      appBar: AppBar(
        title: const Text('設定', style: TextStyle(fontWeight: FontWeight.w800)),
        actions: [IconButton(tooltip: '重新載入', onPressed: _loading ? null : _load, icon: const Icon(Icons.sync_rounded))],
      ),
      body: SafeArea(
        top: false,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 24, 16, 32),
          children: [
            AnimatedSwitcher(
              duration: const Duration(milliseconds: 300),
              switchInCurve: Curves.easeOutCubic,
              child: _loading ? const _SettingsSkeleton(key: ValueKey('loading')) : _CredentialPanel(key: const ValueKey('credentials'), source: _source, saving: _saving, clientIdController: _clientIdController, clientSecretController: _clientSecretController, secretVisible: _secretVisible, onToggleSecret: () => setState(() => _secretVisible = !_secretVisible), onSave: _save, onClear: _clear),
            ),
          ],
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
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(32),
        boxShadow: [BoxShadow(color: AppColors.pastelBlueDeep.withValues(alpha: 0.08), blurRadius: 32, offset: const Offset(0, 16))],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const _HeaderIcon(icon: Icons.key_rounded),
              const SizedBox(width: 16),
              const Text('TDX 憑證', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900, color: AppColors.ink)),
              const Spacer(),
              _SourceChip(source: source),
            ],
          ),
          const SizedBox(height: 24),
          TextField(
            controller: clientIdController,
            textInputAction: TextInputAction.next,
            decoration: const InputDecoration(labelText: 'Client ID', prefixIcon: Icon(Icons.badge_rounded, color: AppColors.pastelBlueDeep)),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: clientSecretController,
            obscureText: !secretVisible,
            decoration: InputDecoration(
              labelText: 'Client Secret',
              prefixIcon: const Icon(Icons.lock_rounded, color: AppColors.pastelBlueDeep),
              suffixIcon: IconButton(tooltip: secretVisible ? '隱藏' : '顯示', onPressed: onToggleSecret, icon: Icon(secretVisible ? Icons.visibility_off_rounded : Icons.visibility_rounded, color: AppColors.muted)),
            ),
          ),
          const SizedBox(height: 24),
          Row(
            children: [
              Expanded(
                child: FilledButton.icon(onPressed: saving ? null : onSave, icon: const Icon(Icons.save_rounded), label: const Text('儲存設定')),
              ),
              const SizedBox(width: 12),
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
      TdxCredentialSource.saved => (Icons.verified_rounded, '已儲存', AppColors.mint),
      TdxCredentialSource.defaults => (Icons.tune_rounded, '預設', AppColors.pastelBlueDeep),
      TdxCredentialSource.none => (Icons.error_outline_rounded, '待設定', AppColors.pastelPinkDeep),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(16)),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 16, color: color),
          const SizedBox(width: 6),
          Text(label, style: TextStyle(color: color, fontWeight: FontWeight.w900, fontSize: 13)),
        ],
      ),
    );
  }
}

class _HeaderIcon extends StatelessWidget {
  const _HeaderIcon({required this.icon});

  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 48,
      height: 48,
      decoration: BoxDecoration(color: AppColors.pastelBlueSoft, borderRadius: BorderRadius.circular(16)),
      child: Icon(icon, color: AppColors.pastelBlueDeep, size: 24),
    );
  }
}

class _SettingsSkeleton extends StatelessWidget {
  const _SettingsSkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 320,
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(32)),
      child: const Center(child: CircularProgressIndicator()),
    );
  }
}
