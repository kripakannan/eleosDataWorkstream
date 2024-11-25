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

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"pdf"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def scrape_item_quantity(item_name):
    """
    Uses Selenium to scrape the exact quantity of an item from a shopping website.
    """
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")  # Run in headless mode
    driver = webdriver.Chrome(options=options)

    try:
        driver.get("https://www.amazon.com")
        search_box = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "twotabsearchtextbox"))
        )
        search_box.clear()
        search_box.send_keys(item_name)
        search_box.send_keys(Keys.RETURN)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".s-main-slot .s-result-item"))
        )

        first_result = driver.find_elements(By.CSS_SELECTOR, ".s-main-slot .s-result-item")[0]
        first_result.click()

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "productTitle"))
        )
        product_title = driver.find_element(By.ID, "productTitle").text

        match = re.search(r"(\d+)\s*(count|pack|pcs|pieces|ct)", product_title, re.IGNORECASE)
        if match:
            return match.group(1)
        else:
            return "Quantity not found"

    except (StaleElementReferenceException, TimeoutException):
        return "Error while scraping. Please retry."
    except Exception as e:
        return f"Error: {e}"
    finally:
        driver.quit()


def parse_extracted_text(extracted_text):
    parsed_data = {}

    def safe_extract(pattern, text, group=1):
        match = re.search(pattern, text)
        if match and len(match.groups()) >= group:
            return match.group(group)
        return "N/A"

    parsed_data["order_date"] = safe_extract(r"Order Placed: (.+)", extracted_text)
    parsed_data["order_number"] = safe_extract(r"Amazon\.com order number: (.+)", extracted_text)
    parsed_data["order_total"] = safe_extract(r"Order Total: (\$[\d.,]+)", extracted_text)
    parsed_data["status"] = "Not Yet Shipped" if "Not Yet Shipped" in extracted_text else "N/A"

    items = []
    item_blocks = re.findall(r"(\d+) of: (.+?)Condition: New\$(\d+\.\d+)", extracted_text, re.DOTALL)

    for item in item_blocks:
        quantity, name, price = item
        quantity = int(quantity)
        existing_item = next((i for i in items if i["name"] == name.strip() and i["price"] == price), None)
        if existing_item:
            existing_item["quantity"] += quantity
        else:
            items.append({"quantity": quantity, "name": name.strip(), "price": price})

    for item in items:
        item["exact_quantity"] = scrape_item_quantity(item["name"])

    parsed_data["items"] = items
    parsed_data["charges"] = {
        "subtotal": safe_extract(r"Item\(s\) Subtotal: (\$[\d.,]+)", extracted_text),
        "shipping": safe_extract(r"Shipping & Handling: (\$[\d.,]+)", extracted_text),
        "total_before_tax": safe_extract(r"Total before tax: (\$[\d.,]+)", extracted_text),
        "estimated_tax": safe_extract(r"Estimated tax to be collected: (\$[\d.,]+)", extracted_text),
        "grand_total": safe_extract(r"Grand Total:\s*(\$[\d.,]+)", extracted_text),
    }

    return parsed_data


def format_parsed_data(parsed_data):
    table_rows = "".join(
        f"<tr><td>{item['quantity']}</td><td>{item['name']}</td><td>${item['price']}</td><td>{item['exact_quantity']}</td></tr>"
        for item in parsed_data["items"]
    )
    items_table_html = f"""
    <table class="table table-striped table-hover">
        <thead class="table-dark">
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
        f"<li class='list-group-item'><strong>{key.replace('_', ' ').title()}:</strong> {value}</li>"
        for key, value in parsed_data["charges"].items()
    )

    return f"""
    <div class="container mt-4">
        <h1 class="my-4">Order Summary:</h1>
        {items_table_html}
        <h3 class="mt-5">Summary of Charges:</h3>
        <ul class="list-group">{charges_html}</ul>
    </div>
    """


@app.route("/", methods=["GET", "POST"])
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
            os.remove(file_path)

        return render_template_string(f"""
        <!doctype html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
            <title>PDF Order Details</title>
        </head>
        <body>
            {formatted_text}
        </body>
        </html>
        """)

    return '''
        <!doctype html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
            <style>
                body {
                    background: linear-gradient(135deg, #ffd700, #1e90ff);
                    min-height: 100vh;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    font-family: 'Arial', sans-serif;
                }
                .upload-container {
                    background-color: #fff;
                    border-radius: 10px;
                    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.3);
                    max-width: 400px;
                    width: 100%;
                    padding: 2rem;
                    text-align: center;
                }
                .upload-container h1 {
                    color: #1e90ff;
                    margin-bottom: 1.5rem;
                }
                .btn-primary {
                    background-color: #ffd700;
                    border-color: #ffd700;
                    color: #1e90ff;
                }
                .btn-primary:hover {
                    background-color: #1e90ff;
                    border-color: #1e90ff;
                    color: #ffd700;
                }
            </style>
            <title>Upload PDF</title>
        </head>
        <body>
            <div class="upload-container">
                <h1>Upload a PDF File</h1>
                <form method="post" enctype="multipart/form-data">
                    <div class="mb-3">
                        <label for="file" class="form-label">Choose a PDF File:</label>
                        <input type="file" name="file" class="form-control" accept="application/pdf" required>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Upload</button>
                </form>
            </div>
        </body>
        </html>
    '''


if __name__ == "__main__":
    app.run(debug=True)