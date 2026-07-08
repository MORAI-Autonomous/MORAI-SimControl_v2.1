import 'package:flutter/material.dart';

void main() {
  runApp(const MoraiSimControlPrototype());
}

class MoraiSimControlPrototype extends StatelessWidget {
  const MoraiSimControlPrototype({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Sim Control Example',
      theme: ThemeData(
        brightness: Brightness.dark,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF3D78C2),
          brightness: Brightness.dark,
        ),
        scaffoldBackgroundColor: const Color(0xFF16161A),
        fontFamily: 'Segoe UI',
        useMaterial3: true,
      ),
      home: const SimControlHome(),
    );
  }
}

class SimControlHome extends StatefulWidget {
  const SimControlHome({super.key});

  @override
  State<SimControlHome> createState() => _SimControlHomeState();
}

class _SimControlHomeState extends State<SimControlHome> {
  bool connected = false;
  int selectedTab = 0;
  final ipController = TextEditingController(text: '127.0.0.1');
  final portController = TextEditingController(text: '20000');

  static const tabs = [
    'UDP Monitor',
    'UDP Control',
    'Camera Sensor',
    'Object Control',
    'Traffic',
    'Lane Control',
    'Path Follow',
    'File Playback',
    'Transform Playback',
  ];

  @override
  void dispose() {
    ipController.dispose();
    portController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            const _MenuStrip(),
            _TcpTitleBar(
              connected: connected,
              ipController: ipController,
              portController: portController,
              onConnect: () => setState(() => connected = true),
              onDisconnect: () => setState(() => connected = false),
            ),
            Expanded(
              child: LayoutBuilder(
                builder: (context, constraints) {
                  final compact = constraints.maxWidth < 980;
                  if (compact) {
                    return Column(
                      children: [
                        SizedBox(
                          height: 230,
                          child: _CommandPanel(connected: connected),
                        ),
                        Expanded(
                          child: _Workspace(
                            tabs: tabs,
                            selectedTab: selectedTab,
                            onTabSelected: (index) {
                              setState(() => selectedTab = index);
                            },
                          ),
                        ),
                      ],
                    );
                  }
                  return Row(
                    children: [
                      SizedBox(
                        width: 360,
                        child: _CommandPanel(connected: connected),
                      ),
                      Expanded(
                        child: _Workspace(
                          tabs: tabs,
                          selectedTab: selectedTab,
                          onTabSelected: (index) {
                            setState(() => selectedTab = index);
                          },
                        ),
                      ),
                    ],
                  );
                },
              ),
            ),
            const SizedBox(height: 220, child: _LogPanel()),
          ],
        ),
      ),
    );
  }
}

class _MenuStrip extends StatelessWidget {
  const _MenuStrip();

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 30,
      color: const Color(0xFF2B2B31),
      padding: const EdgeInsets.symmetric(horizontal: 8),
      child: const Row(
        children: [
          _MenuText('App'),
          SizedBox(width: 18),
          _MenuText('Settings'),
        ],
      ),
    );
  }
}

class _MenuText extends StatelessWidget {
  const _MenuText(this.label);

  final String label;

  @override
  Widget build(BuildContext context) {
    return Text(label, style: const TextStyle(color: Color(0xFFD6D6DA)));
  }
}

class _TcpTitleBar extends StatelessWidget {
  const _TcpTitleBar({
    required this.connected,
    required this.ipController,
    required this.portController,
    required this.onConnect,
    required this.onDisconnect,
  });

  final bool connected;
  final TextEditingController ipController;
  final TextEditingController portController;
  final VoidCallback onConnect;
  final VoidCallback onDisconnect;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 48,
      decoration: const BoxDecoration(
        color: Color(0xFF19191F),
        border: Border(bottom: BorderSide(color: Color(0xFF3B3B45))),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 10),
      child: Row(
        children: [
          Container(
            width: 28,
            height: 28,
            color: const Color(0xFF050507),
            alignment: Alignment.center,
            child: const Text('M', style: TextStyle(fontWeight: FontWeight.w700)),
          ),
          const SizedBox(width: 12),
          const Text('Sim Control Example', style: TextStyle(color: Color(0xFFBFC0C8))),
          const SizedBox(width: 22),
          const Text('IP:', style: TextStyle(color: Color(0xFFA8A8B0))),
          const SizedBox(width: 6),
          _EndpointField(
            width: 126,
            enabled: !connected,
            controller: ipController,
          ),
          const SizedBox(width: 10),
          const Text('PORT:', style: TextStyle(color: Color(0xFFA8A8B0))),
          const SizedBox(width: 6),
          _EndpointField(
            width: 92,
            enabled: !connected,
            controller: portController,
          ),
          const SizedBox(width: 10),
          SizedBox(
            width: 96,
            child: Text(
              connected ? 'Connected' : 'Disconnected',
              style: TextStyle(
                color: connected ? const Color(0xFF64FF75) : const Color(0xFFFF6060),
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          const SizedBox(width: 10),
          SizedBox(
            width: 108,
            height: 34,
            child: FilledButton.tonal(
              onPressed: connected ? onDisconnect : onConnect,
              child: Text(connected ? 'Disconnect' : 'Reconnect'),
            ),
          ),
        ],
      ),
    );
  }
}

class _EndpointField extends StatelessWidget {
  const _EndpointField({
    required this.width,
    required this.enabled,
    required this.controller,
  });

  final double width;
  final bool enabled;
  final TextEditingController controller;

  @override
  Widget build(BuildContext context) {
    if (!enabled) {
      return SizedBox(
        width: width,
        height: 32,
        child: Align(
          alignment: Alignment.centerLeft,
          child: Text(
            controller.text,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(color: Color(0xFF74747D)),
          ),
        ),
      );
    }

    return SizedBox(
      width: width,
      height: 34,
      child: TextField(
        controller: controller,
        style: const TextStyle(color: Color(0xFFF2F2F6), fontSize: 13),
        decoration: InputDecoration(
          filled: true,
          fillColor: const Color(0xFF2A2A34),
          contentPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 7),
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(6),
            borderSide: BorderSide.none,
          ),
        ),
      ),
    );
  }
}

class _CommandPanel extends StatelessWidget {
  const _CommandPanel({required this.connected});

  final bool connected;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.fromLTRB(8, 8, 4, 4),
      padding: const EdgeInsets.all(12),
      decoration: _panelDecoration(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _PanelTitle('Commands'),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _CommandButton('Get Status', enabled: connected),
              _CommandButton('Load Map', enabled: connected),
              _CommandButton('Fixed Step', enabled: connected),
              _CommandButton('Save Data', enabled: connected),
            ],
          ),
          const SizedBox(height: 18),
          const _SectionLabel('Scenario'),
          const SizedBox(height: 8),
          const _MockInput(label: 'Suite path', value: 'samples/default.suite'),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(child: _CommandButton('Load Suite', enabled: connected)),
              const SizedBox(width: 8),
              Expanded(child: _CommandButton('Start', enabled: connected)),
            ],
          ),
          const Spacer(),
          Text(
            connected ? 'Ready to send TCP commands.' : 'Connect to enable simulator commands.',
            style: const TextStyle(color: Color(0xFF9C9CA6)),
          ),
        ],
      ),
    );
  }
}

class _Workspace extends StatelessWidget {
  const _Workspace({
    required this.tabs,
    required this.selectedTab,
    required this.onTabSelected,
  });

  final List<String> tabs;
  final int selectedTab;
  final ValueChanged<int> onTabSelected;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.fromLTRB(4, 8, 8, 4),
      decoration: _panelDecoration(),
      child: Column(
        children: [
          SizedBox(
            height: 46,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
              itemCount: tabs.length,
              separatorBuilder: (_, __) => const SizedBox(width: 6),
              itemBuilder: (context, index) {
                final selected = index == selectedTab;
                return ChoiceChip(
                  selected: selected,
                  label: Text(tabs[index]),
                  onSelected: (_) => onTabSelected(index),
                );
              },
            ),
          ),
          const Divider(height: 1, color: Color(0xFF363641)),
          Expanded(
            child: _MonitorSurface(title: tabs[selectedTab]),
          ),
        ],
      ),
    );
  }
}

class _MonitorSurface extends StatelessWidget {
  const _MonitorSurface({required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(14),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final columns = constraints.maxWidth > 900 ? 3 : 2;
          return GridView.count(
            crossAxisCount: columns,
            crossAxisSpacing: 12,
            mainAxisSpacing: 12,
            childAspectRatio: 1.9,
            children: [
              _MetricTile(title: title, value: 'Idle', caption: 'Current panel state'),
              const _MetricTile(title: 'TCP', value: 'Disconnected', caption: 'Connection status'),
              const _MetricTile(title: 'UDP', value: '0 pkt/s', caption: 'Live receive rate'),
              const _MetricTile(title: 'Scenario', value: 'Ready', caption: 'Runner state'),
              const _MetricTile(title: 'VehicleInfo', value: '--', caption: 'Last payload age'),
              const _MetricTile(title: 'Fixed Step', value: '-- ms', caption: 'ACK latency'),
            ],
          );
        },
      ),
    );
  }
}

class _MetricTile extends StatelessWidget {
  const _MetricTile({
    required this.title,
    required this.value,
    required this.caption,
  });

  final String title;
  final String value;
  final String caption;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF202029),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFF3A3A46)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(color: Color(0xFFB8B8C2))),
          const Spacer(),
          Text(
            value,
            style: const TextStyle(
              fontSize: 24,
              color: Color(0xFFEDEDF2),
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 4),
          Text(caption, style: const TextStyle(color: Color(0xFF858590))),
        ],
      ),
    );
  }
}

class _LogPanel extends StatelessWidget {
  const _LogPanel();

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.fromLTRB(8, 4, 8, 8),
      padding: const EdgeInsets.all(12),
      decoration: _panelDecoration(),
      child: const Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _PanelTitle('Log'),
          SizedBox(height: 8),
          Expanded(
            child: SingleChildScrollView(
              child: Text(
                '[INFO] UI prototype loaded\n'
                '[INFO] TCP endpoint controls are static mock controls\n'
                '[WARN] Backend API is not connected yet',
                style: TextStyle(
                  color: Color(0xFFD6D6DA),
                  fontFamily: 'Consolas',
                  height: 1.35,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _PanelTitle extends StatelessWidget {
  const _PanelTitle(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: const TextStyle(
        fontSize: 16,
        fontWeight: FontWeight.w700,
        color: Color(0xFFF0F0F4),
      ),
    );
  }
}

class _SectionLabel extends StatelessWidget {
  const _SectionLabel(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(text, style: const TextStyle(color: Color(0xFFAFAFBA)));
  }
}

class _CommandButton extends StatelessWidget {
  const _CommandButton(this.label, {required this.enabled});

  final String label;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    return FilledButton.tonal(
      onPressed: enabled ? () {} : null,
      child: Text(label),
    );
  }
}

class _MockInput extends StatelessWidget {
  const _MockInput({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return InputDecorator(
      decoration: InputDecoration(
        labelText: label,
        filled: true,
        fillColor: const Color(0xFF252530),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(6),
          borderSide: BorderSide.none,
        ),
      ),
      child: Text(value, overflow: TextOverflow.ellipsis),
    );
  }
}

BoxDecoration _panelDecoration() {
  return BoxDecoration(
    color: const Color(0xFF1B1B22),
    borderRadius: BorderRadius.circular(8),
    border: Border.all(color: const Color(0xFF363641)),
  );
}
