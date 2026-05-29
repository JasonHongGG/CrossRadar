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

class _LaunchScreenState extends ConsumerState<LaunchScreen> with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  late final Animation<double> _logoScale;
  late final Animation<double> _logoOpacity;
  var _minimumElapsed = false;
  var _navigated = false;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(vsync: this, duration: const Duration(milliseconds: 1150))..forward();
    _logoScale = CurvedAnimation(
      parent: _controller,
      curve: const Interval(0.10, 0.84, curve: Curves.easeOutBack),
    );
    _logoOpacity = CurvedAnimation(
      parent: _controller,
      curve: const Interval(0, 0.42, curve: Curves.easeOut),
    );
    Timer(const Duration(milliseconds: 950), () {
      if (!mounted) return;
      setState(() => _minimumElapsed = true);
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final bundle = ref.watch(mobileBundleProvider);
    _finishWhenReady(bundle);
    return Scaffold(
      body: DecoratedBox(
        decoration: const BoxDecoration(gradient: AppGradients.softBrand),
        child: Stack(
          fit: StackFit.expand,
          children: [
            AnimatedBuilder(
              animation: _controller,
              builder: (context, _) => CustomPaint(painter: _LaunchRailPainter(progress: _controller.value)),
            ),
            SafeArea(
              child: Center(
                child: FadeTransition(
                  opacity: _logoOpacity,
                  child: ScaleTransition(
                    scale: Tween<double>(begin: 0.82, end: 1).animate(_logoScale),
                    child: Container(
                      width: 132,
                      height: 132,
                      padding: const EdgeInsets.all(18),
                      decoration: BoxDecoration(
                        gradient: AppGradients.brand,
                        borderRadius: BorderRadius.circular(8),
                        boxShadow: [BoxShadow(color: AppColors.blue.withValues(alpha: 0.24), blurRadius: 36, offset: const Offset(0, 18))],
                      ),
                      child: DecoratedBox(
                        decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(8)),
                        child: Padding(
                          padding: const EdgeInsets.all(12),
                          child: Image.asset(
                            'logo/logo.png',
                            fit: BoxFit.contain,
                            errorBuilder: (context, error, stackTrace) => const Icon(Icons.radar_rounded, color: AppColors.blue, size: 56),
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
            Positioned(
              left: 40,
              right: 40,
              bottom: 58,
              child: AnimatedOpacity(
                opacity: bundle.isLoading ? 0.62 : 0,
                duration: const Duration(milliseconds: 240),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(999),
                  child: const LinearProgressIndicator(minHeight: 4, backgroundColor: Colors.white, color: AppColors.blue),
                ),
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
          transitionDuration: const Duration(milliseconds: 420),
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

class _LaunchRailPainter extends CustomPainter {
  const _LaunchRailPainter({required this.progress});

  final double progress;

  @override
  void paint(Canvas canvas, Size size) {
    final firstPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 5
      ..strokeCap = StrokeCap.round
      ..shader = const LinearGradient(colors: [AppColors.blue, AppColors.rose]).createShader(Offset.zero & size);
    final secondPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2
      ..strokeCap = StrokeCap.round
      ..color = AppColors.blueDeep.withValues(alpha: 0.10);

    final wave = math.sin(progress * math.pi).clamp(0.0, 1.0);
    final firstPath = Path()
      ..moveTo(-40, size.height * 0.34)
      ..cubicTo(size.width * 0.22, size.height * (0.20 + wave * 0.04), size.width * 0.48, size.height * 0.52, size.width + 40, size.height * 0.36);
    final secondPath = Path()
      ..moveTo(-20, size.height * 0.68)
      ..cubicTo(size.width * 0.30, size.height * 0.78, size.width * 0.70, size.height * (0.48 - wave * 0.03), size.width + 20, size.height * 0.64);
    canvas.drawPath(firstPath, firstPaint..color = firstPaint.color.withValues(alpha: 0.10 + progress * 0.28));
    canvas.drawPath(secondPath, secondPaint);
  }

  @override
  bool shouldRepaint(covariant _LaunchRailPainter oldDelegate) => oldDelegate.progress != progress;
}
