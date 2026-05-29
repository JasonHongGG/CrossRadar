import 'package:flutter/material.dart';

class AppColors {
  static const ink = Color(0xFF243044);
  static const muted = Color(0xFF758097);
  static const surface = Color(0xFFFFFBFF);
  static const panel = Color(0xFFFFFFFF);
  static const rose = Color(0xFFFF8DB8);
  static const roseSoft = Color(0xFFFFE4EE);
  static const blue = Color(0xFF6DA8FF);
  static const blueSoft = Color(0xFFE3F0FF);
  static const mint = Color(0xFF55C7AE);
  static const amber = Color(0xFFFFB84D);
  static const danger = Color(0xFFFF5B7E);
}

ThemeData buildCrossRadarTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: AppColors.rose,
    brightness: Brightness.light,
    primary: AppColors.rose,
    secondary: AppColors.blue,
    surface: AppColors.surface,
  );
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: AppColors.surface,
    appBarTheme: const AppBarTheme(
      elevation: 0,
      backgroundColor: AppColors.surface,
      foregroundColor: AppColors.ink,
      centerTitle: false,
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(18),
        borderSide: BorderSide.none,
      ),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
    ),
    cardTheme: CardThemeData(
      color: AppColors.panel,
      elevation: 0,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(
        foregroundColor: AppColors.ink,
        backgroundColor: Colors.white.withValues(alpha: 0.86),
      ),
    ),
  );
}
