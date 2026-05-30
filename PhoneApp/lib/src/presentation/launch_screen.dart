import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/mobile_bundle_repository.dart';
import '../theme/app_theme.dart';
import 'home_screen.dart';

class LaunchScreen extends ConsumerStatefulWidget {
  const LaunchScreen({super.key});

  @override
  ConsumerState<LaunchScreen> createState() => _LaunchScreenState();
}

class _LaunchScreenState extends ConsumerState<LaunchScreen> with TickerProviderStateMixin {
  late final AnimationController _entranceController;
  late final AnimationController _radarController;
  late final Animation<double> _logoScale;
  late final Animation<double> _logoOpacity;
  late final Animation<Offset> _textOffset;
  late final Animation<double> _textOpacity;
  var _minimumElapsed = false;
  var _navigated = false;

  @override
  void initState() {
    super.initState();
    _entranceController = AnimationController(vsync: this, duration: const Duration(milliseconds: 1400))..forward();
    _radarController = AnimationController(vsync: this, duration: const Duration(milliseconds: 3000))..repeat();

    _logoScale = CurvedAnimation(
      parent: _entranceController,
      curve: const Interval(0.1, 0.7, curve: Curves.easeOutBack),
    );
    _logoOpacity = CurvedAnimation(
      parent: _entranceController,
      curve: const Interval(0.1, 0.5, curve: Curves.easeOut),
    );
    _textOffset = Tween<Offset>(begin: const Offset(0, 0.5), end: Offset.zero).animate(
      CurvedAnimation(
        parent: _entranceController,
        curve: const Interval(0.4, 0.9, curve: Curves.easeOutCubic),
      ),
    );
    _textOpacity = CurvedAnimation(
      parent: _entranceController,
      curve: const Interval(0.4, 0.8, curve: Curves.easeOut),
    );

    Timer(const Duration(milliseconds: 3000), () {
      if (!mounted) return;
      setState(() => _minimumElapsed = true);
    });
  }

  @override
  void dispose() {
    _entranceController.dispose();
    _radarController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final bundle = ref.watch(mobileBundleProvider);
    _finishWhenReady(bundle);
    return Scaffold(
      body: DecoratedBox(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xFFE4EDF7), Color(0xFFFDFBFD), Color(0xFFE8F1FA)],
          ),
        ),
        child: Stack(
          fit: StackFit.expand,
          children: [
            // Radar Animation Background
            AnimatedBuilder(
              animation: _radarController,
              builder: (context, _) => CustomPaint(painter: _RadarPainter(progress: _radarController.value)),
            ),
            SafeArea(
              child: Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    FadeTransition(
                      opacity: _logoOpacity,
                      child: ScaleTransition(
                        scale: Tween<double>(begin: 0.7, end: 1).animate(_logoScale),
                        child: Container(
                          width: 140,
                          height: 140,
                          decoration: BoxDecoration(
                            color: Colors.white,
                            shape: BoxShape.circle,
                            boxShadow: [
                              BoxShadow(color: AppColors.pastelBlueDeep.withValues(alpha: 0.15), blurRadius: 40, spreadRadius: 10, offset: const Offset(0, 16)),
                              BoxShadow(color: AppColors.pastelBlueSoft.withValues(alpha: 0.8), blurRadius: 12, spreadRadius: 2, offset: const Offset(0, 4)),
                            ],
                            border: Border.all(color: Colors.white, width: 4),
                          ),
                          child: Padding(
                            padding: const EdgeInsets.all(16),
                            child: Image.asset(
                              'logo/logo.png',
                              fit: BoxFit.contain,
                              errorBuilder: (context, error, stackTrace) => const Icon(Icons.radar_rounded, color: AppColors.pastelBlueDeep, size: 64),
                            ),
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 24),
                    FadeTransition(
                      opacity: _textOpacity,
                      child: SlideTransition(
                        position: _textOffset,
                        child: const Text(
                          'CrossRadar',
                          style: TextStyle(
                            fontSize: 32,
                            fontWeight: FontWeight.w900,
                            letterSpacing: -0.5,
                            color: AppColors.pastelBlueDeep,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            Positioned(
              left: 0,
              right: 0,
              bottom: 64,
              child: AnimatedOpacity(
                opacity: bundle.isLoading ? 1.0 : 0.0,
                duration: const Duration(milliseconds: 300),
                child: const _CustomLoader(),
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _finishWhenReady(AsyncValue<Object?> bundle) {
    if (_navigated || !_minimumElapsed || bundle.isLoading) return;
    _navigated = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        PageRouteBuilder<void>(
          transitionDuration: const Duration(milliseconds: 600),
          pageBuilder: (context, animation, secondaryAnimation) => const HomeScreen(),
          transitionsBuilder: (context, animation, secondaryAnimation, child) {
            return FadeTransition(
              opacity: CurvedAnimation(parent: animation, curve: Curves.easeOut),
              child: child,
            );
          },
        ),
      );
    });
  }
}

class _RadarPainter extends CustomPainter {
  const _RadarPainter({required this.progress});

  final double progress;

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final maxRadius = math.sqrt(size.width * size.width + size.height * size.height) / 2;

    // Draw concentric circles
    final circlePaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.0;

    for (int i = 1; i <= 6; i++) {
      final baseRadius = maxRadius * (i / 6.0);
      final radius = (baseRadius + (progress * maxRadius / 6.0)) % maxRadius;
      final opacity = 0.15 * (1 - (radius / maxRadius));
      canvas.drawCircle(center, radius, circlePaint..color = AppColors.pastelBlueDeep.withValues(alpha: opacity));
    }

    // Draw sweep
    final sweepPaint = Paint()
      ..style = PaintingStyle.fill
      ..shader = SweepGradient(
        center: Alignment.center,
        startAngle: 0.0,
        endAngle: math.pi * 0.4,
        colors: [
          AppColors.pastelBlueDeep.withValues(alpha: 0.0),
          AppColors.pastelBlueDeep.withValues(alpha: 0.2),
        ],
        transform: GradientRotation(progress * math.pi * 2),
      ).createShader(Rect.fromCircle(center: center, radius: maxRadius));

    canvas.drawArc(Rect.fromCircle(center: center, radius: maxRadius), progress * math.pi * 2, math.pi * 0.4, true, sweepPaint);
  }

  @override
  bool shouldRepaint(covariant _RadarPainter oldDelegate) => oldDelegate.progress != progress;
}

class _CustomLoader extends StatefulWidget {
  const _CustomLoader();

  @override
  State<_CustomLoader> createState() => _CustomLoaderState();
}

class _CustomLoaderState extends State<_CustomLoader> with SingleTickerProviderStateMixin {
  late final AnimationController _loaderController;

  @override
  void initState() {
    super.initState();
    _loaderController = AnimationController(vsync: this, duration: const Duration(milliseconds: 1200))..repeat();
  }

  @override
  void dispose() {
    _loaderController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _loaderController,
      builder: (context, _) {
        return Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: List.generate(3, (index) {
            final delay = index * 0.2;
            final val = (_loaderController.value - delay) % 1.0;
            final scale = val < 0.0 ? 1.0 : (1.0 + math.sin(val * math.pi) * 0.5);
            final opacity = val < 0.0 ? 0.3 : (0.3 + math.sin(val * math.pi) * 0.7);
            
            return Padding(
              padding: const EdgeInsets.symmetric(horizontal: 6),
              child: Transform.scale(
                scale: scale,
                child: Container(
                  width: 10,
                  height: 10,
                  decoration: BoxDecoration(
                    color: AppColors.pastelPinkDeep.withValues(alpha: opacity),
                    shape: BoxShape.circle,
                    boxShadow: [
                      BoxShadow(color: AppColors.pastelPinkDeep.withValues(alpha: opacity * 0.5), blurRadius: 8),
                    ],
                  ),
                ),
              ),
            );
          }),
        );
      },
    );
  }
}
