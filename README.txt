Скрипт для автоматизации работы с Opinion.trade
1) Заполнить файл .env
MULTISIG_ADDRESS - скопировать здесь - https://app.opinion.trade/profile Balance Spot а под ним адрес.

2) Установка
MacOS:
  cd <your_folder> 
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt

Windows:
  cd <your_folder> 
  python -m venv venv
  venv\Scripts\activate
  pip install -r requirements.txt

3) Запуск
MacOS:
  source venv/bin/activate
  python -m uvicorn web.app:app --reload --port 8080

Windows:
  venv\Scripts\activate
  python -m uvicorn web.app:app --reload --port 8080

4) Дальнейшая инструкция http://localhost:8080/static/guide/index.html (либо ссылка в дашборде в меню слева в низу)