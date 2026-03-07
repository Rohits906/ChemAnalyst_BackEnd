@echo off
set "JAVA_HOME=C:\Program Files\Java\jdk-21"
set "KAFKA_DIR=D:\django_projects\chemanalyst_project\backend\kafka_server"

echo Starting Zookeeper...
start "Zookeeper" /min cmd /c "cd /d %KAFKA_DIR% && bin\windows\zookeeper-server-start.bat config\zookeeper.properties"

echo Waiting for Zookeeper to start...
timeout /t 10 /nobreak

echo Starting Kafka...
start "Kafka" /min cmd /c "cd /d %KAFKA_DIR% && bin\windows\kafka-server-start.bat config\server.properties"

echo Kafka and Zookeeper should be starting in separate windows.
