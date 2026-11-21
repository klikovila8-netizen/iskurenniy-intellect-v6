Сборка Windows EXE без установки Python на твоём компьютере

1. Создай аккаунт/войдите на github.com
2. Создай новый репозиторий (можно Public или Private), имя: iskurenniy-intellect
3. Загрузи в репозиторий файлы из этой папки, включая папку .github/workflows.
   Важно: при загрузке через веб-интерфейс GitHub папку workflow нужно добавить через
   Add file -> Create new file, путь .github/workflows/build-windows.yml, и вставить
   содержимое файла из архива, либо загрузить все файлы через GitHub Desktop.
4. Открой вкладку Actions -> Build Windows EXE -> Run workflow.
5. После успешной сборки открой её запуск (зелёная галочка), внизу Artifacts скачай ZIP.
6. Распакуй ZIP. Запускай EXE двойным кликом.

Это автоматическая сборка на сервере GitHub. На твоём компьютере Python не нужен.
