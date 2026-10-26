' Start YDL Studio without a console window.
Option Explicit

Dim fso, shell, root, python
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

root = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = root

If fso.FileExists(root & "\.venv\Scripts\pythonw.exe") Then
    python = """" & root & "\.venv\Scripts\pythonw.exe"""
Else
    python = "pythonw.exe"
End If

shell.Run python & " -m ydl_studio", 0, False
