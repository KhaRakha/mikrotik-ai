# ==============================================================================
# Silent Background Launcher via PowerShell (MikroTik AI Agent)
# ==============================================================================
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$PythonExe = "C:\Users\LENOVO\AppData\Local\Programs\Python\Python314\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python.exe"
}

# Jalankan watchdog.py di background tanpa memunculkan jendela console
Start-Process -FilePath $PythonExe -ArgumentList "service\watchdog.py" -WorkingDirectory $ProjectDir -WindowStyle Hidden
