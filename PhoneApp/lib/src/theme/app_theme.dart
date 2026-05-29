import 'package:flutter/material.dart';

class AppColors {
  static const ink = Color(0xFF2C365E);
  static const muted = Color(0xFF8B9CB6);
  static const surface = Color(0xFFF9FBFF);
  static const panel = Color(0xFFFFFFFF);
  static const panelTint = Color(0xFFF0F5FA);
  
  static const pastelPink = Color(0xFFFFB3C6);
  static const pastelPinkDeep = Color(0xFFFF85A1);
  static const pastelPinkSoft = Color(0xFFFFF0F3);
  
  static const pastelBlue = Color(0xFFA9DEF9);
  static const pastelBlueDeep = Color(0xFF75C9F9);
  static const pastelBlueSoft = Color(0xFFE4F6FF);

  static const cyan = Color(0xFF80EDF7);
  static const mint = Color(0xFFD0F4DE);
  static const amber = Color(0xFFFFD166);
  static const danger = Color(0xFFFF7B93);
  
  static const glassBackground = Color(0x66FFFFFF);
}

class AppGradients {
  static const brand = LinearGradient(colors: [AppColors.pastelBlue, AppColors.pastelPink], begin: Alignment.topLeft, end: Alignment.bottomRight);
  static const softBrand = LinearGradient(colors: [AppColors.pastelBlueSoft, AppColors.pastelPinkSoft], begin: Alignment.topLeft, end: Alignment.bottomRight);
  static const glowGradient = LinearGradient(colors: [Color(0x44A9DEF9), Color(0x44FFB3C6)], begin: Alignment.topLeft, end: Alignment.bottomRight);
}

ThemeData buildCrossRadarTheme() {
  final scheme = ColorScheme.fromSeed(seedColor: AppColors.pastelBlue, brightness: Brightness.light, primary: AppColors.pastelBlueDeep, secondary: AppColors.pastelPinkDeep, surface: AppColors.surface);
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: AppColors.surface,
    appBarTheme: const AppBarTheme(elevation: 0, backgroundColor: AppColors.surface, foregroundColor: AppColors.ink, centerTitle: false, surfaceTintColor: Colors.transparent),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(24), borderSide: BorderSide.none),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
    ),
    cardTheme: CardThemeData(
      color: AppColors.panel,
      elevation: 0,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(foregroundColor: AppColors.ink, backgroundColor: Colors.white.withValues(alpha: 0.86), hoverColor: AppColors.pastelBlueSoft, highlightColor: AppColors.pastelPinkSoft),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: AppColors.pastelBlueDeep,
        foregroundColor: Colors.white,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
      ),
    ),
  );
}
