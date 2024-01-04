import streamlit as st
import pandas as pd
import tabula
import tempfile
import fitz
import pytesseract
import re
from PIL import Image
from io import BytesIO
import os

def read_and_extract_patterns(pdf_data, patterns):
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp:
        temp.write(pdf_data)
        temp_path = temp.name

    with tempfile.NamedTemporaryFile(suffix='.png') as img_temp:
        doc = fitz.open(temp_path)

        # Initialize text as an empty string to collect text from all pages
        text = ""

        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(dpi=170)
            pix.save(img_temp.name, jpg_quality=98)

            img1 = Image.open(img_temp.name)
            page_text = pytesseract.image_to_string(img1, config='--psm 6')

            text += page_text  # Append page text to the overall text

        # Extract values for each pattern
        pattern_values = {}
        for pattern_name, pattern_regex in patterns.items():
            match = re.search(pattern_regex, text, re.IGNORECASE)
            pattern_values[pattern_name] = match.group(1).strip() if match else ''

    return pattern_values

def extract_tables_from_pdf(pdf_file):
    try:
        # Extract tables from the PDF
        tables = tabula.read_pdf(pdf_file, pages='all', multiple_tables=True)
        return tables
    except Exception as e:
        st.error(f"Error extracting tables from {pdf_file.name}: {e}")
        return None

def filter_tables_by_first_cell_value(tables, target_substring):
    filtered_tables = [table for table in tables if not table.empty and len(table.columns) > 0 and str(table.iloc[0, 0]).lower().find(target_substring.lower()) != -1]
    return filtered_tables

def process_and_append_tables(filtered_tables, pdf_filename, appended_tables, total_pdfs, progress_container):
    for i, table in enumerate(filtered_tables):
        # Process the table (remove first 3 rows, rename columns, reset index, and add filename column)
        processed_table = table.iloc[3:].copy()

        # Check the number of columns in processed_table
        if len(processed_table.columns) == 10:  # Adjust this number if needed
            # Add filename column
            processed_table["Filename"] = pdf_filename

            # Reset index
            processed_table.reset_index(drop=True, inplace=True)

            # Rename columns
            processed_table.columns = [
                "Land Item No.",
                "Land Item and Property ID",
                "Notes",
                "% Owned",
                "Land Taxable Value $",
                "Surcharge Taxable Value $",
                "Year 1",
                "Year 2",
                "Year 3",
                "Average Land Value $",
                "Filename"
            ]

            # Fill NaN in "Year 3" with last characters of "Year 2" based on the length of "Year 1"
            processed_table["Year 3"] = processed_table.apply(lambda row: row["Year 2"][-len(row["Year 1"]):] if pd.isna(row["Year 3"]) and not pd.isna(row["Year 2"]) else row["Year 3"], axis=1)
            processed_table["Year 2"] = processed_table.apply(lambda row: row["Year 2"][:len(str(row["Year 1"]))] if pd.notna(row["Year 1"]) else row["Year 2"], axis=1)

            # Append the processed table to the list
            appended_tables.append(processed_table)
        else:
            st.warning(f"Ignoring table in {pdf_filename} due to mismatched number of columns.")

        # Update the progress dynamically
        st.text(f"Processing... {pdf_filename}")

    # Clear the progress container after processing is complete
    progress_container.empty()



def main():
    st.title("Land Tax Assessment Data Extractor")

    # File upload
    pdf_files = st.file_uploader("Upload one or more PDF files", type=["pdf"], accept_multiple_files=True)

    patterns = {
        "Name": r'Name:(.*)',
        "Client ID": r'Client ID:(.*)',
        "Correspondence ID": r'Correspondence ID:(.*)',
        "Issue date": r'Issue date:(.*)',
        "Aggregated taxable land value": r'Aggregated taxable land value(.*)',
        "Less threshold": r'Less threshold(.*)',
        "Subtotal": r'Subtotal(.*)',
        "Total tax payable": r'Total tax payable(.*)',
    }

    if pdf_files:
        total_pdfs = len(pdf_files)
        appended_tables = []
        pattern_values_list = []  # List to store pattern values for each PDF

        # Create an empty container for dynamic progress update
        progress_container = st.empty()

        for pdf_file in pdf_files:
            # Check if the file is a PDF
            if not pdf_file.name.lower().endswith('.pdf'):
                st.warning(f"Skipping non-PDF file: {pdf_file.name}")
                continue

            pdf_data = pdf_file.read()
            pattern_values = read_and_extract_patterns(pdf_data, patterns)

            if pattern_values:
                # Store pattern values in a list for each PDF
                pattern_values_list.append({**pattern_values, "Filename": pdf_file.name})
            else:
                st.warning(f"No values extracted for the specified patterns in {pdf_file.name}.")


            # Extract tables from the PDF
            tables = extract_tables_from_pdf(pdf_file)

            if tables:
                # Filter tables by the first cell value containing the substring
                target_substring = "Land"
                filtered_tables = filter_tables_by_first_cell_value(tables, target_substring)

                if filtered_tables:
                    # Process and append tables
                    process_and_append_tables(filtered_tables, pdf_file.name, appended_tables, total_pdfs, progress_container)

                else:
                    st.warning(f"No tables found with the first cell containing '{target_substring}' in {pdf_file.name}.")

        # Display the concatenated result
        if appended_tables:
            final_result = pd.concat(appended_tables, ignore_index=True)

            # Add a new column "PID" based on the condition
            final_result["PID"] = final_result["Land Item and Property ID"].shift(-1)
            final_result.loc[final_result["Land Item and Property ID"].str.contains("PID"), "PID"] = final_result["Land Item and Property ID"]

            # Remove rows where "Land Item No." is NaN
            final_result = final_result.dropna(subset=["Land Item No."])

            # Reorder the columns with "PID" before "Notes" and reset the index
            final_result = final_result[
                ["Land Item No.", "Land Item and Property ID", "PID", "Notes", "% Owned", "Land Taxable Value $",
                 "Surcharge Taxable Value $", "Year 1", "Year 2", "Year 3", "Average Land Value $", "Filename"]
            ].reset_index(drop=True)

            if pattern_values_list:
                pattern_values_df = pd.DataFrame(pattern_values_list)
                final_result = pd.merge(pattern_values_df, final_result, on="Filename", how="left")


            st.header("Final Result:")
            st.write(final_result)
        else:
            st.warning("No tables found in the provided PDF files.")


if __name__ == "__main__":
    main()

