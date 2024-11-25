from flask import Flask, request, render_template_string
from pdf_utils import extract_text_from_pdf  # Import the utility function
import os
import re
from werkzeug.utils import secure_filename
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
    NoSuchElementException,
)
import re
import time

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"pdf"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename):
    """Check if the uploaded file is a PDF."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def scrape_item_quantity(item_name):
    """
    Uses Selenium to scrape the exact quantity of an item from a shopping website.
    """
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")  # Run in headless mode
    driver = webdriver.Chrome(options=options)

    try:
        # Navigate to Amazon
        driver.get("https://www.amazon.com")

        # Search for the item name
        search_box = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "twotabsearchtextbox"))
        )
        search_box.clear()
        search_box.send_keys(item_name)
        search_box.send_keys(Keys.RETURN)

        # Wait for the search results to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".s-main-slot .s-result-item"))
        )

        # Re-fetch the first result to avoid stale element error
        first_result = driver.find_elements(By.CSS_SELECTOR, ".s-main-slot .s-result-item")[0]
        first_result.click()

        # Wait for the product page to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "productTitle"))
        )

        # Scrape the product title
        product_title = driver.find_element(By.ID, "productTitle").text

        # Extract quantity from the title
        match = re.search(r"(\d+)\s*(count|pack|pcs|pieces|ct)", product_title, re.IGNORECASE)
        if match:
            return match.group(1)  # Return the quantity
        else:
            return "Quantity not found"

    except StaleElementReferenceException:
        # Refetch the element if stale
        return "Error: Element became stale. Retry scraping."

    except TimeoutException:
        return "Error: Timed out while waiting for elements."

    except Exception as e:
        return f"Error: {e}"

    finally:
        driver.quit()


def parse_extracted_text(extracted_text):
    """
    Parses the extracted text to identify order details, items, and charges.
    """
    parsed_data = {}

    def safe_extract(pattern, text, group=1):
        match = re.search(pattern, text)
        if match and len(match.groups()) >= group:
            return match.group(group)
        return "N/A"

    # Extract order summary details
    parsed_data["order_date"] = safe_extract(r"Order Placed: (.+)", extracted_text)
    parsed_data["order_number"] = safe_extract(r"Amazon\.com order number: (.+)", extracted_text)
    parsed_data["order_total"] = safe_extract(r"Order Total: (\$[\d.,]+)", extracted_text)
    parsed_data["status"] = "Not Yet Shipped" if "Not Yet Shipped" in extracted_text else "N/A"

    # Extract items ordered
    items = []
    item_blocks = re.findall(r"(\d+) of: (.+?)Condition: New\$(\d+\.\d+)", extracted_text, re.DOTALL)

    for item in item_blocks:
        quantity, name, price = item
        quantity = int(quantity)

        # Consolidate items with same name and price
        existing_item = next((i for i in items if i["name"] == name.strip() and i["price"] == price), None)
        if existing_item:
            existing_item["quantity"] += quantity
        else:
            items.append({"quantity": quantity, "name": name.strip(), "price": price})

    # Enrich items with exact quantity using web scraping
    for item in items:
        item["exact_quantity"] = scrape_item_quantity(item["name"])

    parsed_data["items"] = items

    # Extract charges
    parsed_data["charges"] = {
        "subtotal": safe_extract(r"Item\(s\) Subtotal: (\$[\d.,]+)", extracted_text),
        "shipping": safe_extract(r"Shipping & Handling: (\$[\d.,]+)", extracted_text),
        "total_before_tax": safe_extract(r"Total before tax: (\$[\d.,]+)", extracted_text),
        "estimated_tax": safe_extract(r"Estimated tax to be collected: (\$[\d.,]+)", extracted_text),
        "grand_total": safe_extract(r"Grand Total:\s*(\$[\d.,]+)", extracted_text),
    }

    return parsed_data


def format_parsed_data(parsed_data):
    """
    Formats parsed data into structured HTML with a table for items.
    """
    table_rows = "".join(
        f"<tr><td>{item['quantity']}</td><td>{item['name']}</td><td>${item['price']}</td><td>{item['exact_quantity']}</td></tr>"
        for item in parsed_data["items"]
    )
    items_table_html = f"""
    <table border="1" style="width: 100%; border-collapse: collapse; text-align: left;">
        <thead>
            <tr>
                <th>Quantity</th>
                <th>Item Name</th>
                <th>Price</th>
                <th>Exact Quantity</th>
            </tr>
        </thead>
        <tbody>
            {table_rows}
        </tbody>
    </table>
    """

    charges_html = "".join(
        f"<li><strong>{key.replace('_', ' ').title()}:</strong> {value}</li>"
        for key, value in parsed_data["charges"].items()
    )

    return f"""
    <h1>Order Summary:</h1>
    {items_table_html}
    <h3>Summary of Charges:</h3>
    <ul>{charges_html}</ul>
    """


@app.route("/", methods=["GET", "POST"])
def upload_pdf():
    if request.method == "POST":
        if "file" not in request.files:
            return "No file uploaded.", 400

        pdf_file = request.files["file"]
        if pdf_file.filename == "" or not allowed_file(pdf_file.filename):
            return "Invalid file type. Please upload a PDF.", 400

        filename = secure_filename(pdf_file.filename)
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        pdf_file.save(file_path)

        try:
            extracted_text = extract_text_from_pdf(file_path)
            parsed_data = parse_extracted_text(extracted_text)
            formatted_text = format_parsed_data(parsed_data)
        except Exception as e:
            return f"An error occurred: {e}", 500
        finally:
            os.remove(file_path)  # Clean up uploaded file

        return f"<h1>Extracted Text:</h1>{formatted_text}"

    return '''
        <!doctype html>
        <title>Upload PDF</title>
        <h1>Upload a PDF file</h1>
        <form method="post" enctype="multipart/form-data">
            <input type="file" name="file" accept="application/pdf">
            <input type="submit" value="Upload">
        </form>
    '''


if __name__ == "__main__":
    app.run(debug=True)