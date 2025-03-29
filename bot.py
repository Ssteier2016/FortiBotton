import random
import time
import pickle
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Configurar opciones para evitar detección
chrome_options = Options()
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
chrome_options.add_experimental_option("useAutomationExtension", False)

# Ruta a ChromeDriver
service = Service("chromedriver.exe")
driver = webdriver.Chrome(service=service, options=chrome_options)

driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

# Ruta para guardar las cookies
COOKIES_PATH = "cookies.pkl"

def save_cookies(driver, path):
    """Guarda las cookies en un archivo."""
    with open(path, "wb") as file:
        pickle.dump(driver.get_cookies(), file)
    print("✅ Cookies guardadas correctamente.")

def load_cookies(driver, path):
    """Carga las cookies desde un archivo."""
    if os.path.exists(path):
        with open(path, "rb") as file:
            cookies = pickle.load(file)
            for cookie in cookies:
                try:
                    driver.add_cookie(cookie)
                except:
                    print("⚠️ Error al cargar una cookie.")
        print("✅ Cookies cargadas correctamente.")
    else:
        print("❌ No se encontraron cookies.")

def click_button_if_present(text):
    """Hace clic en un botón si está presente."""
    try:
        button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, f"//button[div[text()='{text}']]"))
        )
        button.click()
        time.sleep(2)
    except:
        print(f"⚠️ Botón '{text}' no encontrado o no disponible.")

def select_random_dropdown(select_id):
    """Selecciona un valor aleatorio en un menú desplegable."""
    try:
        dropdown = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, select_id))
        )
        dropdown.click()
        time.sleep(1)
        dropdown.send_keys(str(random.randint(1, 28)))  # Simula valores aleatorios
        dropdown.send_keys(Keys.ENTER)
    except:
        print(f"⚠️ Dropdown {select_id} no disponible.")

def answer_random_question():
    """Responde preguntas aleatorias (menús desplegables, opciones de selección, etc.)."""
    try:
        elements = driver.find_elements(By.CLASS_NAME, "react-select__input")
        for element in elements:
            element.click()
            time.sleep(1)
            element.send_keys(Keys.ARROW_DOWN)
            element.send_keys(Keys.ENTER)
            time.sleep(1)
    except:
        print("⚠️ No se encontró una pregunta seleccionable.")

# Abrir la página de Surveytime
driver.get("https://surveytime.io/profiler")

# Intentar cargar cookies para evitar iniciar sesión
load_cookies(driver, COOKIES_PATH)
driver.refresh()  # Refrescar la página para aplicar cookies

# Verificar si el usuario necesita iniciar sesión
if "Iniciar sesión" in driver.page_source:
    click_button_if_present("Iniciar sesión")
    input("🔵 Inicia sesión manualmente y presiona ENTER para continuar...")  
    save_cookies(driver, COOKIES_PATH)  # Guardar cookies después del inicio de sesión

# Continuar con la encuesta
click_button_if_present("//button[div[contains(text(),'Empezar ya')]]")
frames = driver.find_elements(By.TAG_NAME, "iframe")
print(f"🔍 Encontrados {len(frames)} iframes.")

for i, frame in enumerate(frames):
    driver.switch_to.frame(frame)
    if "Empezar ya" in driver.page_source:
        print(f"✅ Botón encontrado dentro del iframe {i}.")
        click_button_if_present("Empezar ya")
        driver.switch_to.default_content()
        break
    driver.switch_to.default_content()
    
def click_button_with_scroll(xpath):
    """Hace scroll hasta el botón y lo presiona."""
    try:
        button = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, xpath))
        )
        driver.execute_script("arguments[0].scrollIntoView();", button)  # Desplazar hasta el botón
        time.sleep(1)  # Esperar un poco más
        button.click()
        time.sleep(2)
    except:
        print(f"⚠️ No se pudo hacer clic en el botón {xpath}")

click_button_with_scroll("//button[div[text()='Empezar ya']]")
def click_add_answers():
    """Hace clic en el botón 'Añadir respuestas' si está disponible."""
    try:
        button = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//button[div[text()='Añadir respuestas']]"))
        )
        driver.execute_script("arguments[0].scrollIntoView();", button)  # Hacer scroll si está tapado
        time.sleep(1)  # Esperar un poco más
        button.click()
        time.sleep(2)
        print("✅ Botón 'Añadir respuestas' presionado.")
        
    except:
        print("⚠️ Botón 'Añadir respuestas' no encontrado o no disponible.")
        

# Llamar a la función después de hacer clic en 'Empezar ya'
click_add_answers()
def select_random_multiple_choice():
    """Selecciona respuestas aleatorias en preguntas tipo 'multiple choice' usando XPath."""
    try:
        # Encuentra todas las opciones dentro de la pregunta actual usando XPath
        options = driver.find_elements(By.XPATH, "//*[@id='root']/div/div[1]/div/div[1]/div/div[2]/div/div/div")

        if options:
            random_option = random.choice(options)  # Selecciona una opción al azar
            driver.execute_script("arguments[0].scrollIntoView();", random_option)  # Asegura que sea visible
            time.sleep(1)  # Pequeña pausa
            random_option.click()  # Hace clic en la opción
            time.sleep(1)
            print("✅ Opción seleccionada en pregunta múltiple choice.")
               # Verificar si aparece el menú desplegable después de "Empezar ya"
        elif is_element_present(By.XPATH, "//*[@id='root']/div/div[1]/div/div[1]/div/div[2]/div/div/div[1]/div[2]/div"):
            print("📂 Menú desplegable detectado, seleccionando una opción aleatoria...")
            select_random_dropdown("react-select-5-input")  # Ajusta el ID según corresponda
        else:
            print("⚠️ No se encontraron opciones en esta pregunta.")

    except Exception as e:
        print(f"⚠️ Error al seleccionar opción múltiple choice: {e}")

# Llamar a la función después de 'Añadir respuestas'
select_random_multiple_choice()
click_button_if_present("siguiente")
time.sleep(3)  # Esperar carga inicial

while True:
    try:
        # Verificar si hay una pregunta de fecha de nacimiento
  # Verificar si aparece el menú desplegable después de "Empezar ya"
        if is_element_present(By.XPATH, "//*[@id='root']/div/div[1]/div/div[1]/div/div[2]/div/div/div[1]/div[2]/div"):
            print("📂 Menú desplegable detectado, seleccionando una opción aleatoria...")
            select_random_dropdown("react-select-5-input")  # Ajusta el ID según corresponda
        
        else:
            while True:
                # Intentar hacer clic en "Añadir respuestas" si está presente
                if click_button_if_present("Añadir respuestas"):
                    print("➕ Se presionó 'Añadir respuestas'. Seleccionando opciones nuevamente...")
                    time.sleep(2)  # Pequeña pausa antes de seleccionar opciones
                    select_random_multiple_choice()  # Seleccionar opciones de multiple choice
                else:
                    break  # Si no encuentra el botón, sale del loop interno

            # Intentar hacer clic en el botón "Siguiente" si está presente
            click_button_if_present("siguiente")

        time.sleep(2)  # Pequeña pausa antes de la siguiente pregunta

    except Exception as e:
        print(f"🎉 Encuesta finalizada o error inesperado: {e}")
        break


driver.quit()
