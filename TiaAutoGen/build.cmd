@echo off
setlocal
set TIAVER=%~1
if "%TIAVER%"=="" set TIAVER=21
echo Building TiaAutoGen for TIA Portal V%TIAVER% ...
dotnet build "%~dp0TiaAutoGen.csproj" -c Release /p:TiaVersion=%TIAVER%
if errorlevel 1 (
  echo.
  echo Build failed. Check that TIA Portal V%TIAVER% is installed, or pass the API folder:
  echo   build.cmd 20
  echo   dotnet build /p:TiaApiDir="C:\Program Files\Siemens\Automation\Portal V21\PublicAPI\V21\net48"
)
endlocal
