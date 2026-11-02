@echo off
setlocal
cd /d "%~dp0.."
set "CLOUDSDK_PYTHON=%CD%\.venv\Scripts\python.exe"
set "CLOUDSDK_CORE_DISABLE_USAGE_REPORTING=true"
if exist ".tools\windows-ca-bundle.pem" set "CLOUDSDK_CORE_CUSTOM_CA_CERTS_FILE=%CD%\.tools\windows-ca-bundle.pem"
echo Sign in using the Google account your teammate added to rovvsm-4c944.
call ".tools\google-cloud-sdk\bin\gcloud.cmd" auth application-default login --project=rovvsm-4c944
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m rov_mlbb.firestore_export --project rovvsm-4c944 --list-collections
if errorlevel 1 exit /b 1
echo Login and collection listing completed. No database documents were modified.
