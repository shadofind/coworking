# Коворкинг «Точка»

Веб-приложение для бронирования рабочих мест и переговорных. Серверная часть построена на Django, клиентская — на HTML, CSS и JavaScript без фронтенд-фреймворков.

## Запуск локально

```powershell
py -m venv .venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py createsuperuser
python manage.py runserver
```

Откройте `http://127.0.0.1:8000/`. Панель управления Django доступна по адресу `/admin/`. Письма в режиме разработки выводятся в консоль.

Демо-команда создаёт места, тарифы, услуги, резидентов и не менее 30 броней. У демонстрационных резидентов пароли не заданы — создайте пользователя через регистрацию или панель Django.