import 'package:flutter/material.dart';

import 'presentation/launch_screen.dart';
import 'theme/app_theme.dart';

class CrossRadarApp extends StatelessWidget {
  const CrossRadarApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(debugShowCheckedModeBanner: false, title: 'CrossRadar', theme: buildCrossRadarTheme(), home: const LaunchScreen());
  }
}
