@echo off
rem Launch the JiveTalker editor: jivetalker.bat voice_script.txt [more jivetalker edit options]
rem Finds the virtual environment in %JIVETALKER_VENV%, then .venv next to this file, then %USERPROFILE%\venv\kokoro.
rem With no arguments, opens the editor with no script: create one, open one, or try the demo.
rem Other subcommands work too: jivetalker.bat mixer ..., jivetalker.bat render ...
setlocal
set "EXE="
if defined JIVETALKER_VENV if exist "%JIVETALKER_VENV%\Scripts\jivetalker.exe" set "EXE=%JIVETALKER_VENV%\Scripts\jivetalker.exe"
if not defined EXE if exist "%~dp0.venv\Scripts\jivetalker.exe" set "EXE=%~dp0.venv\Scripts\jivetalker.exe"
if not defined EXE if exist "%USERPROFILE%\venv\kokoro\Scripts\jivetalker.exe" set "EXE=%USERPROFILE%\venv\kokoro\Scripts\jivetalker.exe"
if not defined EXE (
  echo jivetalker not found. Install it ^(see README.md^) or set JIVETALKER_VENV to the venv folder. 1>&2
  exit /b 1
)
if "%~1"=="" (
  "%EXE%" edit
  exit /b %errorlevel%
)
set "FIRST=%~1"
for %%S in (mixer render check preview sing voice edit) do if /i "%FIRST%"=="%%S" goto :passthru
if "%FIRST:~0,1%"=="-" goto :passthru
"%EXE%" edit %*
exit /b %errorlevel%
:passthru
"%EXE%" %*
exit /b %errorlevel%
