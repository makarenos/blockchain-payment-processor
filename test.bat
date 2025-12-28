@echo off
REM Windows test runner for Blockchain Payment Processor

if "%1"=="" goto help
if "%1"=="install" goto install
if "%1"=="test" goto test
if "%1"=="test-fast" goto test-fast
if "%1"=="test-coverage" goto test-coverage
if "%1"=="test-auth" goto test-auth
if "%1"=="test-deposits" goto test-deposits
if "%1"=="test-withdrawals" goto test-withdrawals
if "%1"=="test-admin" goto test-admin
if "%1"=="test-webhooks" goto test-webhooks
if "%1"=="test-models" goto test-models
if "%1"=="test-services" goto test-services
if "%1"=="test-integration" goto test-integration
if "%1"=="clean" goto clean
if "%1"=="help" goto help
goto help

:help
echo Available commands:
echo.
echo   test.bat install          - Install dependencies
echo   test.bat test              - Run all tests with coverage
echo   test.bat test-fast         - Run tests without coverage (faster)
echo   test.bat test-coverage     - Run tests with detailed coverage
echo   test.bat test-auth         - Run authentication tests
echo   test.bat test-deposits     - Run deposit tests
echo   test.bat test-withdrawals  - Run withdrawal tests
echo   test.bat test-admin        - Run admin tests
echo   test.bat test-webhooks     - Run webhook tests
echo   test.bat test-models       - Run model tests
echo   test.bat test-services     - Run service tests
echo   test.bat test-integration  - Run integration tests
echo   test.bat clean             - Clean up generated files
echo.
goto end

:install
echo Installing dependencies...
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-cov pytest-mock
echo Dependencies installed successfully!
goto end

:test
echo Running all tests with coverage...
pytest -v --cov=app --cov-report=html --cov-report=term-missing
goto end

:test-fast
echo Running tests without coverage...
pytest -v --no-cov -x
goto end

:test-coverage
echo Running tests with detailed coverage...
pytest --cov=app --cov-report=html:htmlcov --cov-report=term-missing --cov-report=xml --cov-fail-under=80
echo.
echo Coverage report generated in htmlcov\index.html
goto end

:test-auth
echo Running authentication tests...
pytest tests\test_auth.py -v
goto end

:test-deposits
echo Running deposit tests...
pytest tests\test_deposits.py -v
goto end

:test-withdrawals
echo Running withdrawal tests...
pytest tests\test_withdrawals.py -v
goto end

:test-admin
echo Running admin tests...
pytest tests\test_admin.py -v
goto end

:test-webhooks
echo Running webhook tests...
pytest tests\test_webhooks.py -v
goto end

:test-models
echo Running model tests...
pytest tests\test_models.py -v
goto end

:test-services
echo Running service tests...
pytest tests\test_services.py -v
goto end

:test-integration
echo Running integration tests...
pytest tests\test_integration.py -v
goto end

:clean
echo Cleaning up generated files...
if exist htmlcov rmdir /s /q htmlcov
if exist .coverage del .coverage
if exist coverage.xml del coverage.xml
if exist .pytest_cache rmdir /s /q .pytest_cache
if exist test.db del test.db
echo Cleanup completed!
goto end

:end