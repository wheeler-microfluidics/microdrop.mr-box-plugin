@echo off
REM Do not excecute script if `PKG_NAME` environment variable is not set.
REM
REM See: https://github.com/sci-bots/microdrop/issues/250
IF NOT DEFINED PKG_NAME ( 
  echo Do not excecute script since `PKG_NAME` environment variable is not set.
  echo See https://github.com/sci-bots/microdrop/issues/250 for more info.
  exit /b
)

REM Strip `microdrop.` prefix (i.e., first 10 characters) from package name.
set PLUGIN_NAME=%PKG_NAME:~10%
REM Replace hyphen characters with underscores.
set PLUGIN_NAME=%PLUGIN_NAME:-=_%

REM Link installed plugin into Conda MicroDrop activated plugins directory.
call "%PREFIX%\Scripts\activate.bat" "%PREFIX%" & python -m mpm.bin.api enable %PLUGIN_NAME%
echo Linked `%PLUGIN_NAME%` into MicroDrop activated plugins directory. > "%PREFIX%\.messages.txt"

REM Load plugin by default
call "%PREFIX%\Scripts\activate.bat" "%PREFIX%" & microdrop-config edit --append plugins.enabled %PLUGIN_NAME%
echo Configured MicroDrop to load `%PLUGIN_NAME%` by default. >> "%PREFIX%\.messages.txt"
