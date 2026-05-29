import 'package:flutter/material.dart';

class AppColors {
  static const ink = Color(0xFF18233A);
  static const muted = Color(0xFF6D7890);
  static const surface = Color(0xFFF5FAFF);
  static const panel = Color(0xFFFFFFFF);
  static const panelTint = Color(0xFFEAF3FF);
  static const rose = Color(0xFFFF6FAE);
  static const roseDeep = Color(0xFFE9458F);
  static const roseSoft = Color(0xFFFFE5F0);
  static const blue = Color(0xFF2F80ED);
  static const blueDeep = Color(0xFF2455C9);
  static const blueSoft = Color(0xFFE4F0FF);
  static const cyan = Color(0xFF49C6E8);
  static const mint = Color(0xFF55C7AE);
  static const amber = Color(0xFFFFB84D);
  static const danger = Color(0xFFFF5B7E);
}

class AppGradients {
  static const brand = LinearGradient(colors: [AppColors.blueDeep, AppColors.blue, AppColors.rose], begin: Alignment.topLeft, end: Alignment.bottomRight);

  static const softBrand = LinearGradient(colors: [Color(0xFFEAF3FF), Color(0xFFFFECF5)], begin: Alignment.topLeft, end: Alignment.bottomRight);
}

ThemeData buildCrossRadarTheme() {
  final scheme = ColorScheme.fromSeed(seedColor: AppColors.blue, brightness: Brightness.light, primary: AppColors.blue, secondary: AppColors.rose, surface: AppColors.surface);
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: AppColors.surface,
    appBarTheme: const AppBarTheme(elevation: 0, backgroundColor: AppColors.surface, foregroundColor: AppColors.ink, centerTitle: false, surfaceTintColor: Colors.transparent),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: BorderSide.none),
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
    ),
    cardTheme: CardThemeData(
      color: AppColors.panel,
      elevation: 0,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(foregroundColor: AppColors.ink, backgroundColor: Colors.white.withValues(alpha: 0.86), hoverColor: AppColors.blueSoft, highlightColor: AppColors.roseSoft),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: AppColors.blue,
        foregroundColor: Colors.white,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
    ),
  );
}
