# FleasoDaPos - Sistema POS

Sistema de Punto de Venta (POS) desarrollado con Django 5, TailwindCSS y HTMX.

## Requisitos Previos

- Python 3.10+
- Node.js & NPM (para estilos)
- Git

## Instalación Local

1.  **Clonar el repositorio**
    ```bash
    git clone <url-del-repositorio>
    cd fleasodapos
    ```

2.  **Crear entorno virtual**
    ```bash
    python -m venv venv
    # Windows
    venv\Scripts\activate
    # Linux/Mac
    source venv/bin/activate
    ```

3.  **Instalar dependencias Python**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Instalar dependencias Frontend**
    ```bash
    npm install
    ```

5.  **Generar estilos CSS**
    ```bash
    npm run build
    ```

6.  **Migraciones y Superusuario**
    ```bash
    python manage.py migrate
    python manage.py createsuperuser
    ```

7.  **Ejecutar**
    ```bash
    python manage.py runserver
    ```

---

## Guía de Despliegue en Producción (VPS Ubuntu + Nginx)

Esta guía asume que tienes un servidor Ubuntu 22.04 LTS limpio y acceso root/sudo.

### 1. Preparar el Servidor

Actualizar paquetes e instalar dependencias:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv nginx git -y
```

### 2. Clonar el Proyecto

```bash
cd /var/www
sudo git clone <tu-repo-url> fleasodapos
sudo chown -R $USER:$USER fleasodapos
cd fleasodapos
```

### 3. Configurar Entorno Python

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn
```

### 4. Configurar Variables de Entorno

Crear archivo `.env`:
```bash
nano .env
```
Contenido:
```env
DEBUG=False
SECRET_KEY=tu_clave_secreta_segura_generada
ALLOWED_HOSTS=tu-dominio.com,www.tu-dominio.com,IP_DEL_VPS
DATABASE_URL=sqlite:///db.sqlite3
```

### 5. Archivos Estáticos y Base de Datos

```bash
# Asegúrate de ejecutar tailwind si es necesario o sube el css compilado
# Si compilas en servidor:
# sudo apt install npm
# npm install && npm run build

python manage.py collectstatic
python manage.py migrate
python manage.py createsuperuser
```

Asignar permisos a la DB y media (para SQLite):
```bash
sudo chown -R www-data:www-data db.sqlite3
sudo chown -R www-data:www-data media/
sudo chmod 775 db.sqlite3
sudo chmod 775 media/
# Importante: la carpeta contenedora también debe ser escribible por www-data para SQLite
sudo chown :www-data .
sudo chmod 775 .
```

### 6. Configurar Gunicorn (Servidor de Aplicación)

Crear archivo de servicio systemd:
```bash
sudo nano /etc/systemd/system/fleasodapos.service
```

Contenido:
```ini
[Unit]
Description=Gunicorn daemon for FleasoDaPos
After=network.target

[Service]
User=root
Group=www-data
WorkingDirectory=/var/www/fleasodapos
ExecStart=/var/www/fleasodapos/venv/bin/gunicorn --access-logfile - --workers 3 --bind unix:/var/www/fleasodapos/fleasodapos.sock core.wsgi:application

[Install]
WantedBy=multi-user.target
```
*(Nota: Se usa User=root temporalmente para simplificar permisos con SQLite en carpetas root, idealmente usa tu usuario no-root y ajusta dueños de carpeta)*

Iniciar servicio:
```bash
sudo systemctl start fleasodapos
sudo systemctl enable fleasodapos
```

### 7. Configurar Nginx (Proxy Inverso)

Crear configuración de sitio:
```bash
sudo nano /etc/nginx/sites-available/fleasodapos
```

Contenido:
```nginx
server {
    listen 80;
    server_name tu-dominio.com IP_DEL_VPS;

    location = /favicon.ico { access_log off; log_not_found off; }
    
    # Archivos Estáticos
    location /static/ {
        root /var/www/fleasodapos;
    }

    # Archivos Media (Imágenes subidas)
    location /media/ {
        root /var/www/fleasodapos;
    }

    # Proxy a Gunicorn
    location / {
        include proxy_params;
        proxy_pass http://unix:/var/www/fleasodapos/fleasodapos.sock;
    }
}
```

Activar sitio:
```bash
sudo ln -s /etc/nginx/sites-available/fleasodapos /etc/nginx/sites-enabled
sudo nginx -t
sudo systemctl restart nginx
```

### 8. Seguridad (SSL con Certbot) -- Opcional pero recomendado

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d tu-dominio.com
```

¡Listo! Tu sistema POS debería estar online.
