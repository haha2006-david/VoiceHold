Option Explicit

' Keep this file ASCII-only; read Unicode paths from the user's environment.
Dim shell, paths, python, script, fso
Set shell = CreateObject("WScript.Shell")
Set paths = shell.Environment("User")
python = paths("VoiceHoldPython")
script = paths("VoiceHoldScript")
Set fso = CreateObject("Scripting.FileSystemObject")
If fso.FileExists(python) And fso.FileExists(script) Then
    shell.CurrentDirectory = fso.GetParentFolderName(script)
    shell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & script & Chr(34), 0, False
End If
