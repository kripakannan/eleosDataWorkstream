from PyPDF2 import PdfReader
from selenium import webdriver
from selenium.webdriver.common.by import By
import time
import re

def extract_text_from_pdf(pdf_path):
    reader = PdfReader(pdf_path)
    pdf_text = ""
    for page in reader.pages:
        pdf_text += page.extract_text()
    return pdf_text

def setup_selenium():
    """
    Sets up the Selenium WebDriver.
    """
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=options)
    return driver

def fetch_dynamic_order_data(order_number):
    """
    Fetches live order item quantities and details using Selenium.
    """
    driver = setup_selenium()
    item_quantities = {}
    try:
        # Replace with the URL of the order tracking or detail page
        driver.get(f"https://www.example.com/track-order/{order_number}")
        time.sleep(3)  # Allow time for the page to load

        # Locate the item list table or section
        items = driver.find_elements(By.XPATH, "//div[@class='order-item']")
        for item in items:
            item_name = item.find_element(By.XPATH, ".//span[@class='item-name']").text
            quantity = item.find_element(By.XPATH, ".//span[@class='item-quantity']").text

            # Clean the extracted quantity
            cleaned_quantity = int(re.search(r"(\d+)", quantity).group(1)) if re.search(r"(\d+)", quantity) else 0

            # Add to the dictionary
            item_quantities[item_name.strip()] = cleaned_quantity

        return {"item_quantities": item_quantities}
    except Exception as e:
        print(f"Error during Selenium scraping: {e}")
        return {"item_quantities": {}}
    finally:
        driver.quit()