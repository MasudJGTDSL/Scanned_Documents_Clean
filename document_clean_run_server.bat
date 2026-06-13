@echo off
echo Starting OCR Document Processor...
echo.
echo Open your browser at: http://127.0.0.1:8006
echo Press Ctrl+C to stop the server.
echo.
"f:\Scanned_Documents_Clean\env\Scripts\python.exe" "f:\Scanned_Documents_Clean\manage.py" runserver 8006
pause
