/// Example Flutter application demonstrating the Experimentation Platform SDK.
///
/// This app shows:
///  - SDK initialisation
///  - Feature flag evaluation (with live boolean display)
///  - Experiment assignment retrieval
///  - Event tracking (fire-and-forget)
///  - Offline fallback (SharedPreferences)
import 'package:flutter/material.dart';
import 'package:experimentation_sdk/experimentation_sdk.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  final client = ExperimentationClient(
    config: const SdkConfig(
      apiKey: 'YOUR_API_KEY_HERE',
      baseUrl: 'https://api.getexperimently.com',
      cacheTtl: Duration(minutes: 5),
      offlineFallback: true,
    ),
  );

  await client.init();

  runApp(ExperimentationApp(client: client));
}

class ExperimentationApp extends StatelessWidget {
  final ExperimentationClient client;

  const ExperimentationApp({super.key, required this.client});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Experimentation SDK Demo',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.blue),
        useMaterial3: true,
      ),
      home: HomePage(client: client),
    );
  }
}

class HomePage extends StatefulWidget {
  final ExperimentationClient client;

  const HomePage({super.key, required this.client});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  static const _userId = 'demo-user-123';

  bool _darkModeEnabled = false;
  String? _checkoutVariant;
  String _status = 'Tap a button to evaluate a flag or get an assignment.';
  bool _loading = false;

  Future<void> _evaluateFlag() async {
    setState(() {
      _loading = true;
      _status = 'Evaluating flag…';
    });

    try {
      final enabled = await widget.client.evaluateFlag(
        'dark-mode',
        _userId,
        attributes: {'platform': 'flutter'},
      );
      setState(() {
        _darkModeEnabled = enabled;
        _status = 'dark-mode flag: ${enabled ? "ENABLED" : "DISABLED"}';
      });
    } catch (e) {
      setState(() => _status = 'Error: $e');
    } finally {
      setState(() => _loading = false);
    }
  }

  Future<void> _getAssignment() async {
    setState(() {
      _loading = true;
      _status = 'Fetching experiment assignment…';
    });

    try {
      final variant = await widget.client.getAssignment(
        'checkout-experiment',
        _userId,
      );
      setState(() {
        _checkoutVariant = variant;
        _status = 'checkout-experiment variant: ${variant ?? "not assigned"}';
      });
    } catch (e) {
      setState(() => _status = 'Error: $e');
    } finally {
      setState(() => _loading = false);
    }
  }

  Future<void> _trackEvent() async {
    await widget.client.track(
      'demo_button_clicked',
      _userId,
      properties: {'source': 'flutter-example', 'screen': 'home'},
    );
    setState(() => _status = 'Event "demo_button_clicked" tracked (fire-and-forget).');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
        title: const Text('Experimentation SDK'),
      ),
      body: Padding(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Status card
            Card(
              color: Colors.blue.shade50,
              child: Padding(
                padding: const EdgeInsets.all(16.0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Status',
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(
                            fontWeight: FontWeight.bold,
                          ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      _status,
                      style: Theme.of(context).textTheme.bodyMedium,
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 24),

            // State display
            ListTile(
              title: const Text('dark-mode enabled'),
              trailing: Icon(
                _darkModeEnabled ? Icons.check_circle : Icons.cancel,
                color: _darkModeEnabled ? Colors.green : Colors.red,
              ),
            ),
            ListTile(
              title: const Text('checkout-experiment variant'),
              trailing: Text(
                _checkoutVariant ?? 'none',
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      fontWeight: FontWeight.bold,
                    ),
              ),
            ),
            const SizedBox(height: 24),

            // Action buttons
            FilledButton(
              onPressed: _loading ? null : _evaluateFlag,
              child: const Text('Evaluate "dark-mode" Flag'),
            ),
            const SizedBox(height: 12),
            FilledButton.tonal(
              onPressed: _loading ? null : _getAssignment,
              child: const Text('Get "checkout-experiment" Assignment'),
            ),
            const SizedBox(height: 12),
            OutlinedButton(
              onPressed: _loading ? null : _trackEvent,
              child: const Text('Track Event (fire-and-forget)'),
            ),

            if (_loading) ...[
              const SizedBox(height: 24),
              const Center(child: CircularProgressIndicator()),
            ],
          ],
        ),
      ),
    );
  }
}
