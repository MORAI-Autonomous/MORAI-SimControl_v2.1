# MORAI Sim Control Flutter UI Prototype

Static Flutter/Dart UI prototype for comparing a Flutter desktop layout with the current DearPyGUI app.

This prototype does not connect to the simulator. It only sketches the shell:

- TCP endpoint bar
- Connect/disconnect state
- Left command panel
- Right monitor area
- Bottom log panel

## Run

Flutter is not currently installed on this machine. After installing Flutter, run:

```powershell
cd C:\Dev\MORAI-SimControl_v2.1\prototypes\flutter_ui
flutter create . --platforms=windows,linux
flutter run -d windows
```

On Linux:

```bash
cd /path/to/MORAI-SimControl_v2.1/prototypes/flutter_ui
flutter create . --platforms=windows,linux
flutter run -d linux
```
