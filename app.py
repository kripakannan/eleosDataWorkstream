from flask import Flask, request
from pdf_utils import extract_text_from_pdf  # Import the utility function
import os
import re

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


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

    # Consolidate items with same name and price
    for item in item_blocks:
        quantity, name, price = item
        quantity = int(quantity)  # Convert quantity to integer for addition

        # Check if item with same name and price already exists
        existing_item = next((i for i in items if i["name"] == name.strip() and i["price"] == price), None)

        if existing_item:
            existing_item["quantity"] += quantity  # Add the quantity to the existing item
        else:
            items.append({"quantity": quantity, "name": name.strip(), "price": price})

    parsed_data["items"] = items

    # Extract charges
    parsed_data["charges"] = {
        "subtotal": safe_extract(r"Item\(s\) Subtotal: (\$[\d.,]+)", extracted_text),
        "shipping": safe_extract(r"Shipping & Handling: (\$[\d.,]+)", extracted_text),
        "total_before_tax": safe_extract(r"Total before tax: (\$[\d.,]+)", extracted_text),
        "estimated_tax": safe_extract(r"Estimated tax to be collected: (\$[\d.,]+)", extracted_text),
        "grand_total": safe_extract(r"Grand Total:\s*(\$[\d.,]+)", extracted_text),
    }

    # Extract shipping address
    address_match = re.search(
        r"Shipping Address:\n(.+?)\n(.+?)\n(.+?)\n(.+)", extracted_text, re.DOTALL
    )
    parsed_data["shipping_address"] = {
        "name": address_match.group(1) if address_match and len(address_match.groups()) >= 4 else "N/A",
        "address_line_1": address_match.group(2) if address_match and len(address_match.groups()) >= 4 else "N/A",
        "address_line_2": address_match.group(3) if address_match and len(address_match.groups()) >= 4 else "N/A",
        "country": address_match.group(4) if address_match and len(address_match.groups()) >= 4 else "N/A",
    }

    # Extract payment information
    payment_method = safe_extract(r"Payment Method:\n(.+)", extracted_text)
    billing_address_match = re.search(
        r"Billing address\n(.+?)\n(.+?)\n(.+)", extracted_text, re.DOTALL
    )
    parsed_data["payment_information"] = {
        "method": payment_method,
        "billing_address": {
            "name": billing_address_match.group(1) if billing_address_match and len(
                billing_address_match.groups()) >= 3 else "N/A",
            "address_line_1": billing_address_match.group(2) if billing_address_match and len(
                billing_address_match.groups()) >= 3 else "N/A",
            "country": billing_address_match.group(3) if billing_address_match and len(
                billing_address_match.groups()) >= 3 else "N/A",
        },
    }

    return parsed_data

def format_parsed_data(parsed_data):
    """
    Formats parsed data into structured HTML with a table for items.
    """
    # Generate table for items
    table_rows = "".join(
        f"<tr><td>{item['quantity']}</td><td>{item['name']}</td><td>${item['price']}</td></tr>"
        for item in parsed_data["items"]
    )
    items_table_html = f"""
    <table border="1" style="width: 100%; border-collapse: collapse; text-align: left;">
        <thead>
            <tr>
                <th>Quantity</th>
                <th>Item Name</th>
                <th>Price</th>
            </tr>
        </thead>
        <tbody>
            {table_rows}
        </tbody>
    </table>
    """

    # Format charges
    charges_html = "".join(
        f"<li><strong>{key.replace('_', ' ').title()}:</strong> {value}</li>"
        for key, value in parsed_data["charges"].items()
    )

    # Format shipping address
    shipping_address = parsed_data["shipping_address"]

    # Format payment information
    payment_info = parsed_data["payment_information"]

    return f"""
    <h1>Order Summary:</h1>
    <p><strong>Order Date:</strong> {parsed_data['order_date']}</p>
    <p><strong>Order Number:</strong> {parsed_data['order_number']}</p>
    <p><strong>Order Total:</strong> {parsed_data['order_total']}</p>
    <p><strong>Status:</strong> {parsed_data['status']}</p>

    <h2>Items Ordered:</h2>
    {items_table_html}

    <h3>Summary of Charges:</h3>
    <ul>{charges_html}</ul>

    <h3>Shipping Address:</h3>
    <p>{shipping_address['name']}</p>
    <p>{shipping_address['address_line_1']}</p>
    <p>{shipping_address['address_line_2']}</p>
    <p>{shipping_address['country']}</p>

    <h3>Payment Information:</h3>
    <p><strong>Payment Method:</strong> {payment_info['method']}</p>
    <p><strong>Billing Address:</strong> {payment_info['billing_address']['name']}, {payment_info['billing_address']['address_line_1']}, {payment_info['billing_address']['country']}</p>
    """

@app.route("/", methods=["GET", "POST"])
def upload_pdf():
    if request.method == "POST":
        if "file" not in request.files:
            return "No file uploaded.", 400

        pdf_file = request.files["file"]
        if pdf_file.filename == "":
            return "No selected file.", 400

        file_path = os.path.join(app.config["UPLOAD_FOLDER"], pdf_file.filename)
        pdf_file.save(file_path)

        # Use the utility function to extract text
        extracted_text = extract_text_from_pdf(file_path)

        # Parse and format the extracted text
        parsed_data = parse_extracted_text(extracted_text)
        formatted_text = format_parsed_data(parsed_data)

        return f"<h1>Extracted Text:</h1>{formatted_text}"

    return '''
        <!doctype html>
        <title>Upload PDF</title>
        <h1>Upload a PDF file</h1>
        <form method="post" enctype="multipart/form-data">
            <input type="file" name="file">
            <input type="submit" value="Upload">
        </form>
    '''


if __name__ == "__main__":
    app.run(debug=True)