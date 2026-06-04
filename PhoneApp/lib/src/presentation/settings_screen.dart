import 'dart:math' as math;
import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/credential_store.dart';
import '../services/app_settings_service.dart';
import '../theme/app_theme.dart';

class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key, this.credentialStore = const TdxCredentialStore()});

  final TdxCredentialStore credentialStore;

  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> with SingleTickerProviderStateMixin {
  late final AnimationController _entranceController;

  @override
  void initState() {
    super.initState();
    _entranceController = AnimationController(vsync: this, duration: const Duration(milliseconds: 1000));
    _entranceController.forward();
  }

  @override
  void dispose() {
    _entranceController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      extendBodyBehindAppBar: true,
      backgroundColor: AppColors.surface,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        surfaceTintColor: Colors.transparent,
        flexibleSpace: ClipRRect(
          child: BackdropFilter(
            filter: ImageFilter.blur(sigmaX: 16, sigmaY: 16),
            child: Container(color: AppColors.surface.withValues(alpha: 0.6)),
          ),
        ),
        title: const Text('設定', style: TextStyle(fontWeight: FontWeight.w900, letterSpacing: 1.2)),
        centerTitle: true,
      ),
      body: SafeArea(
        bottom: false,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(24, 32, 24, 64),
          children: [
            _StaggeredEntrance(
              controller: _entranceController,
              index: 0,
              child: _SmartKeyCard(credentialStore: widget.credentialStore),
            ),
            const SizedBox(height: 32),
            _StaggeredEntrance(
              controller: _entranceController,
              index: 1,
              child: const _InteractiveRadarController(),
            ),
          ],
        ),
      ),
    );
  }
}

class _StaggeredEntrance extends StatelessWidget {
  const _StaggeredEntrance({required this.controller, required this.index, required this.child});
  final AnimationController controller;
  final int index;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final start = (index * 0.15).clamp(0.0, 1.0);
    final end = (start + 0.6).clamp(0.0, 1.0);
    final animation = CurvedAnimation(parent: controller, curve: Interval(start, end, curve: Curves.easeOutCubic));

    return AnimatedBuilder(
      animation: animation,
      builder: (context, child) {
        return Opacity(
          opacity: animation.value,
          child: Transform.translate(
            offset: Offset(0, 40 * (1 - animation.value)),
            child: child,
          ),
        );
      },
      child: child,
    );
  }
}

// -----------------------------------------------------------------------------
// 1. Smart Key Card (TDX Credentials)
// -----------------------------------------------------------------------------
class _SmartKeyCard extends StatefulWidget {
  const _SmartKeyCard({required this.credentialStore});
  final TdxCredentialStore credentialStore;

  @override
  State<_SmartKeyCard> createState() => _SmartKeyCardState();
}

class _SmartKeyCardState extends State<_SmartKeyCard> {
  final _clientIdController = TextEditingController();
  final _clientSecretController = TextEditingController();
  var _source = TdxCredentialSource.none;
  var _loading = true;
  var _saving = false;
  var _expanded = false;

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
    HapticFeedback.mediumImpact();
    setState(() => _saving = true);
    await widget.credentialStore.save(TdxCredentials(clientId: _clientIdController.text, clientSecret: _clientSecretController.text));
    await Future.delayed(const Duration(milliseconds: 400)); // Artificial feeling of progress
    if (!mounted) return;
    setState(() {
      _source = TdxCredentialSource.saved;
      _saving = false;
      _expanded = false; // Auto close on success
    });
  }

  Future<void> _clear() async {
    HapticFeedback.lightImpact();
    setState(() => _saving = true);
    await widget.credentialStore.clear();
    await Future.delayed(const Duration(milliseconds: 300));
    if (!mounted) return;
    setState(() {
      _saving = false;
    });
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    final isSaved = _source == TdxCredentialSource.saved;
    final isNone = _source == TdxCredentialSource.none;

    return AnimatedContainer(
      duration: const Duration(milliseconds: 500),
      curve: Curves.easeOutCubic,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(32),
        boxShadow: [
          BoxShadow(
            color: (isSaved ? AppColors.mint : AppColors.pastelBlueDeep).withValues(alpha: _expanded ? 0.15 : 0.08),
            blurRadius: _expanded ? 32 : 16,
            offset: Offset(0, _expanded ? 16 : 8),
          )
        ],
        border: Border.all(color: Colors.white, width: 2),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(30),
        child: Material(
          color: Colors.transparent,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              InkWell(
                onTap: _loading ? null : () {
                  HapticFeedback.selectionClick();
                  setState(() => _expanded = !_expanded);
                },
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Row(
                    children: [
                      _KeyIconStatus(isSaved: isSaved, isLoading: _loading),
                      const SizedBox(width: 20),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text('TDX Key', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900, color: AppColors.ink)),
                            const SizedBox(height: 2),
                            AnimatedSwitcher(
                              duration: const Duration(milliseconds: 300),
                              child: Text(
                                _loading ? '驗證中...' : (isSaved ? '已安全加密儲存' : (isNone ? '點擊以設定金鑰' : '使用系統預設憑證')),
                                key: ValueKey('status_$_loading$_source'),
                                style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: isSaved ? AppColors.mint : AppColors.muted),
                              ),
                            ),
                          ],
                        ),
                      ),
                      AnimatedRotation(
                        turns: _expanded ? 0.5 : 0,
                        duration: const Duration(milliseconds: 400),
                        curve: Curves.easeOutBack,
                        child: Container(
                          padding: const EdgeInsets.all(8),
                          decoration: BoxDecoration(color: AppColors.surface, shape: BoxShape.circle),
                          child: const Icon(Icons.keyboard_arrow_down_rounded, color: AppColors.muted, size: 20),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              AnimatedSize(
                duration: const Duration(milliseconds: 400),
                curve: Curves.easeOutCubic,
                child: _expanded ? _buildExpandedForm() : const SizedBox.shrink(),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildExpandedForm() {
    return Container(
      padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Divider(height: 1, color: AppColors.surface),
          const SizedBox(height: 24),
          _GlassTextField(
            controller: _clientIdController,
            icon: Icons.fingerprint_rounded,
            hint: 'Client ID',
          ),
          const SizedBox(height: 16),
          _GlassTextField(
            controller: _clientSecretController,
            icon: Icons.password_rounded,
            hint: 'Client Secret',
            obscure: true,
          ),
          const SizedBox(height: 24),
          Row(
            children: [
              Expanded(
                child: _AnimatedActionButton(
                  onTap: _saving ? null : _save,
                  isBusy: _saving,
                  label: '儲存',
                  icon: Icons.lock_outline_rounded,
                  color: AppColors.pastelBlueDeep,
                ),
              ),
              const SizedBox(width: 12),
              _AnimatedActionButton(
                onTap: _saving ? null : _clear,
                isBusy: false,
                iconOnly: true,
                icon: Icons.delete_outline_rounded,
                color: AppColors.pastelPinkDeep,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _KeyIconStatus extends StatelessWidget {
  const _KeyIconStatus({required this.isSaved, required this.isLoading});
  final bool isSaved;
  final bool isLoading;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 56,
      height: 56,
      decoration: BoxDecoration(
        color: isSaved ? AppColors.mint.withValues(alpha: 0.15) : AppColors.pastelBlueSoft,
        borderRadius: BorderRadius.circular(20),
      ),
      child: Center(
        child: isLoading
            ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.pastelBlueDeep))
            : AnimatedSwitcher(
                duration: const Duration(milliseconds: 300),
                transitionBuilder: (child, anim) => ScaleTransition(scale: anim, child: FadeTransition(opacity: anim, child: child)),
                child: Icon(
                  isSaved ? Icons.verified_user_rounded : Icons.key_rounded,
                  key: ValueKey(isSaved),
                  color: isSaved ? AppColors.mint : AppColors.pastelBlueDeep,
                  size: 28,
                ),
              ),
      ),
    );
  }
}

class _GlassTextField extends StatelessWidget {
  const _GlassTextField({required this.controller, required this.icon, required this.hint, this.obscure = false});
  final TextEditingController controller;
  final IconData icon;
  final String hint;
  final bool obscure;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: AppColors.surface.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: Colors.white, width: 2),
      ),
      child: TextField(
        controller: controller,
        obscureText: obscure,
        style: const TextStyle(fontWeight: FontWeight.w600, color: AppColors.ink, fontSize: 15),
        decoration: InputDecoration(
          hintText: hint,
          hintStyle: const TextStyle(color: AppColors.muted, fontWeight: FontWeight.w500),
          prefixIcon: Icon(icon, color: AppColors.pastelBlueDeep, size: 20),
          border: InputBorder.none,
          enabledBorder: InputBorder.none,
          focusedBorder: InputBorder.none,
          filled: false,
          contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
        ),
      ),
    );
  }
}

class _AnimatedActionButton extends StatelessWidget {
  const _AnimatedActionButton({required this.onTap, required this.isBusy, this.label, required this.icon, required this.color, this.iconOnly = false});
  final VoidCallback? onTap;
  final bool isBusy;
  final String? label;
  final IconData icon;
  final Color color;
  final bool iconOnly;

  @override
  Widget build(BuildContext context) {
    return AnimatedContainer(
      duration: const Duration(milliseconds: 300),
      height: 56,
      width: iconOnly ? 56 : null,
      decoration: BoxDecoration(
        color: isBusy ? color.withValues(alpha: 0.5) : color,
        borderRadius: BorderRadius.circular(20),
        boxShadow: [if (!isBusy) BoxShadow(color: color.withValues(alpha: 0.3), blurRadius: 12, offset: const Offset(0, 4))],
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(20),
          onTap: onTap,
          child: Center(
            child: AnimatedSwitcher(
              duration: const Duration(milliseconds: 200),
              child: isBusy
                  ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                  : Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(icon, color: Colors.white, size: 22),
                        if (!iconOnly && label != null) ...[
                          const SizedBox(width: 8),
                          Text(label!, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 16)),
                        ]
                      ],
                    ),
            ),
          ),
        ),
      ),
    );
  }
}

// -----------------------------------------------------------------------------
// 2. Interactive Radar Controller (Geofence Settings)
// -----------------------------------------------------------------------------
class _InteractiveRadarController extends ConsumerWidget {
  const _InteractiveRadarController();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(appSettingsProvider);
    final service = ref.read(appSettingsProvider.notifier);

    return Container(
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.9),
        borderRadius: BorderRadius.circular(40),
        boxShadow: [BoxShadow(color: AppColors.pastelBlueDeep.withValues(alpha: 0.06), blurRadius: 40, offset: const Offset(0, 16))],
        border: Border.all(color: Colors.white, width: 2),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(38),
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 16, sigmaY: 16),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 32, horizontal: 24),
            child: Column(
              children: [
                _RadarToggleWidget(
                  isActive: settings.enableGeofence,
                  onToggle: () {
                    HapticFeedback.mediumImpact();
                    service.updateSettings(settings.copyWith(enableGeofence: !settings.enableGeofence));
                  },
                ),
                const SizedBox(height: 32),
                AnimatedSize(
                  duration: const Duration(milliseconds: 500),
                  curve: Curves.easeOutCubic,
                  alignment: Alignment.topCenter,
                  child: settings.enableGeofence
                      ? Column(
                          children: [
                            _SegmentedTriggerControl(
                              isPeriodic: settings.triggerMode == 'periodic',
                              onChanged: (isPeriodic) {
                                HapticFeedback.selectionClick();
                                service.updateSettings(settings.copyWith(triggerMode: isPeriodic ? 'periodic' : 'once'));
                              },
                            ),
                            AnimatedSize(
                              duration: const Duration(milliseconds: 400),
                              curve: Curves.easeOutCubic,
                              child: settings.triggerMode == 'periodic'
                                  ? Padding(
                                      padding: const EdgeInsets.only(top: 16),
                                      child: _CompactSlider(
                                        icon: Icons.timer_rounded,
                                        value: settings.periodicInterval.toDouble(),
                                        min: 10,
                                        max: 300,
                                        label: '${settings.periodicInterval}s',
                                        color: AppColors.amber,
                                        onChanged: (val) => service.updateState(settings.copyWith(periodicInterval: val.toInt())),
                                        onChangeEnd: (val) => service.saveSettings(),
                                      ),
                                    )
                                  : const SizedBox.shrink(),
                            ),
                            const SizedBox(height: 16),
                            const Divider(height: 1, color: AppColors.surface),
                            const SizedBox(height: 16),
                            _VisualRadiusController(
                              radius: settings.geofenceRadius,
                              showOnMap: settings.showRadiusOnMap,
                              onRadiusChanged: (val) => service.updateState(settings.copyWith(geofenceRadius: val)),
                              onRadiusChangeEnd: (val) => service.saveSettings(),
                              onToggleMapDisplay: () {
                                HapticFeedback.lightImpact();
                                service.updateSettings(settings.copyWith(showRadiusOnMap: !settings.showRadiusOnMap));
                              },
                            ),
                          ],
                        )
                      : const SizedBox.shrink(),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _RadarToggleWidget extends StatelessWidget {
  const _RadarToggleWidget({required this.isActive, required this.onToggle});
  final bool isActive;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onToggle,
      child: Column(
        children: [
          SizedBox(
            width: 140,
            height: 140,
            child: Stack(
              alignment: Alignment.center,
              children: [
                if (isActive) ...[
                  _PulseRing(delay: 0, color: AppColors.pastelBlueDeep.withValues(alpha: 0.2)),
                  _PulseRing(delay: 600, color: AppColors.pastelPinkDeep.withValues(alpha: 0.15)),
                ],
                AnimatedContainer(
                  duration: const Duration(milliseconds: 400),
                  curve: Curves.easeOutBack,
                  width: isActive ? 80 : 72,
                  height: isActive ? 80 : 72,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: isActive ? AppColors.pastelBlueDeep : AppColors.surface,
                    boxShadow: [
                      if (isActive) BoxShadow(color: AppColors.pastelBlueDeep.withValues(alpha: 0.4), blurRadius: 24, spreadRadius: 4),
                      if (!isActive) const BoxShadow(color: Colors.black12, blurRadius: 8, offset: Offset(0, 4)),
                    ],
                    border: Border.all(color: Colors.white, width: isActive ? 4 : 2),
                  ),
                  child: Center(
                    child: AnimatedSwitcher(
                      duration: const Duration(milliseconds: 300),
                      transitionBuilder: (child, anim) => RotationTransition(turns: anim, child: FadeTransition(opacity: anim, child: child)),
                      child: Icon(
                        isActive ? Icons.radar_rounded : Icons.power_settings_new_rounded,
                        key: ValueKey(isActive),
                        color: isActive ? Colors.white : AppColors.muted,
                        size: 32,
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          AnimatedDefaultTextStyle(
            duration: const Duration(milliseconds: 300),
            style: TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w900,
              color: isActive ? AppColors.pastelBlueDeep : AppColors.muted,
              letterSpacing: 1.5,
            ),
            child: Text(isActive ? 'RADAR ACTIVE' : 'RADAR OFFLINE'),
          ),
        ],
      ),
    );
  }
}

class _PulseRing extends StatefulWidget {
  const _PulseRing({required this.delay, required this.color});
  final int delay;
  final Color color;

  @override
  State<_PulseRing> createState() => _PulseRingState();
}

class _PulseRingState extends State<_PulseRing> with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(vsync: this, duration: const Duration(milliseconds: 2000));
    Future.delayed(Duration(milliseconds: widget.delay), () {
      if (mounted) _controller.repeat();
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, child) {
        return Transform.scale(
          scale: 0.5 + (_controller.value * 1.2),
          child: Opacity(
            opacity: 1.0 - _controller.value,
            child: Container(
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                border: Border.all(color: widget.color, width: 4),
              ),
            ),
          ),
        );
      },
    );
  }
}

class _SegmentedTriggerControl extends StatelessWidget {
  const _SegmentedTriggerControl({required this.isPeriodic, required this.onChanged});
  final bool isPeriodic;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 56,
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(28),
        border: Border.all(color: Colors.white, width: 2),
      ),
      child: Stack(
        children: [
          AnimatedAlign(
            duration: const Duration(milliseconds: 300),
            curve: Curves.easeOutCubic,
            alignment: isPeriodic ? Alignment.centerRight : Alignment.centerLeft,
            child: FractionallySizedBox(
              widthFactor: 0.5,
              child: Container(
                decoration: BoxDecoration(
                  color: AppColors.pastelBlueDeep,
                  borderRadius: BorderRadius.circular(28),
                  boxShadow: [BoxShadow(color: AppColors.pastelBlueDeep.withValues(alpha: 0.3), blurRadius: 8, offset: const Offset(0, 4))],
                ),
              ),
            ),
          ),
          Row(
            children: [
              Expanded(
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTap: () => onChanged(false),
                  child: Center(
                    child: AnimatedDefaultTextStyle(
                      duration: const Duration(milliseconds: 200),
                      style: TextStyle(fontWeight: FontWeight.w900, fontSize: 15, color: !isPeriodic ? Colors.white : AppColors.muted),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.looks_one_rounded, size: 20, color: !isPeriodic ? Colors.white : AppColors.muted),
                          const SizedBox(width: 8),
                          const Text('單次'),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
              Expanded(
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTap: () => onChanged(true),
                  child: Center(
                    child: AnimatedDefaultTextStyle(
                      duration: const Duration(milliseconds: 200),
                      style: TextStyle(fontWeight: FontWeight.w900, fontSize: 15, color: isPeriodic ? Colors.white : AppColors.muted),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.all_inclusive_rounded, size: 20, color: isPeriodic ? Colors.white : AppColors.muted),
                          const SizedBox(width: 8),
                          const Text('定期'),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _VisualRadiusController extends StatelessWidget {
  const _VisualRadiusController({required this.radius, required this.showOnMap, required this.onRadiusChanged, required this.onRadiusChangeEnd, required this.onToggleMapDisplay});
  final double radius;
  final bool showOnMap;
  final ValueChanged<double> onRadiusChanged;
  final ValueChanged<double> onRadiusChangeEnd;
  final VoidCallback onToggleMapDisplay;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        GestureDetector(
          onTap: onToggleMapDisplay,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            width: 44,
            height: 44,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: showOnMap ? AppColors.pastelPinkDeep.withValues(alpha: 0.15) : Colors.transparent,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: showOnMap ? Colors.transparent : AppColors.surface, width: 2),
            ),
            child: AnimatedSwitcher(
              duration: const Duration(milliseconds: 200),
              transitionBuilder: (child, animation) => ScaleTransition(scale: animation, child: child),
              child: Icon(
                showOnMap ? Icons.my_location_rounded : Icons.location_disabled_rounded,
                key: ValueKey(showOnMap),
                color: showOnMap ? AppColors.pastelPinkDeep : AppColors.muted,
                size: 20,
              ),
            ),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: SliderTheme(
            data: SliderTheme.of(context).copyWith(
              activeTrackColor: AppColors.pastelPinkDeep,
              inactiveTrackColor: AppColors.surface,
              thumbColor: AppColors.pastelPinkDeep,
              overlayColor: AppColors.pastelPinkDeep.withValues(alpha: 0.2),
              trackHeight: 6,
              thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 10),
              overlayShape: const RoundSliderOverlayShape(overlayRadius: 20),
            ),
            child: Slider(
              value: radius,
              min: 50,
              max: 2000,
              onChanged: onRadiusChanged,
              onChangeEnd: onRadiusChangeEnd,
            ),
          ),
        ),
        const SizedBox(width: 8),
        SizedBox(
          width: 52,
          child: Text('${radius.toInt()}m', textAlign: TextAlign.right, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w900, color: AppColors.pastelPinkDeep)),
        ),
      ],
    );
  }
}

class _CompactSlider extends StatelessWidget {
  const _CompactSlider({required this.icon, required this.value, required this.min, required this.max, required this.label, required this.color, required this.onChanged, required this.onChangeEnd});
  final IconData icon;
  final double value;
  final double min;
  final double max;
  final String label;
  final Color color;
  final ValueChanged<double> onChanged;
  final ValueChanged<double> onChangeEnd;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Container(
          width: 44,
          height: 44,
          alignment: Alignment.center,
          decoration: BoxDecoration(color: color.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(12)),
          child: Icon(icon, color: color, size: 20),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: SliderTheme(
            data: SliderTheme.of(context).copyWith(
              activeTrackColor: color,
              inactiveTrackColor: AppColors.surface,
              thumbColor: color,
              overlayColor: color.withValues(alpha: 0.2),
              trackHeight: 6,
              thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 10),
              overlayShape: const RoundSliderOverlayShape(overlayRadius: 20),
            ),
            child: Slider(
              value: value,
              min: min,
              max: max,
              onChanged: onChanged,
              onChangeEnd: onChangeEnd,
            ),
          ),
        ),
        const SizedBox(width: 8),
        SizedBox(
          width: 52,
          child: Text(label, textAlign: TextAlign.right, style: TextStyle(fontSize: 16, fontWeight: FontWeight.w900, color: color)),
        ),
      ],
    );
  }
}
