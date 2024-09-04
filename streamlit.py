import streamlit as st
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from webdriver_manager.chrome import ChromeDriverManager
import time
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import re
import schedule
import threading
import pandas as pd
from io import StringIO
import matplotlib.pyplot as plt

# PII Patterns to detect in network logs (example patterns for email and phone)
PII_PATTERNS = {
    'Email': r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+',
    'Phone': r'\+?[1-9]\d{1,14}',
}

def setup_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    caps = DesiredCapabilities.CHROME.copy()
    caps['goog:loggingPrefs'] = {'performance': 'ALL'}

    options.set_capability('goog:loggingPrefs', caps['goog:loggingPrefs'])

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    return driver


def get_network_logs(driver):
    logs = driver.get_log('performance')
    return logs


def extract_tags_from_logs(logs, check_pii=False):
    tags = []
    unique_pii = set()  # Set to store unique PII data
    for log in logs:
        log_message = log['message']

        if 'Network.requestWillBeSent' in log_message:
            # Facebook Pixel
            if re.search(r'facebook\.com\/tr', log_message):
                tags.append(("Facebook Pixel", extract_load_time(log_message)))

            # Google Ads
            if re.search(r'google\.(com|[a-z.]+)\/ads', log_message):
                tags.append(("Google Ads", extract_load_time(log_message)))

            # LinkedIn Conversion
            if re.search(r'linkedin\.(com|[a-z.]+)\/(li|liads\.js)', log_message):
                tags.append(("LinkedIn Conversion", extract_load_time(log_message)))

            # Floodlight/Google DoubleClick
            if re.search(r'doubleclick\.net\/(activity|dc)', log_message) or re.search(
                    r'google\.(com|[a-z.]+)\/(click|hover)', log_message):
                tags.append(("Google DoubleClick/Floodlight", extract_load_time(log_message)))

        # Privacy Compliance: Check for PII
        if check_pii:
            for label, pattern in PII_PATTERNS.items():
                pii_matches = re.findall(pattern, log_message)
                if pii_matches:
                    unique_pii.update(pii_matches)  # Add unique PII to the set

    return tags, unique_pii


def extract_load_time(log_message):
    load_time = re.search(r'"responseTime":(\d+)', log_message)
    return int(load_time.group(1)) if load_time else None


def send_email(to_email, element_name, element_text, tags):
    from_email = "saibhola.shankar@gmail.com"  # Replace with your email
    from_password = "cxdydvxsuumhizuz"  # Replace with your email password

    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Subject'] = "Third-Party Tags Fired on Element Click"

    body = f"Element Clicked: {element_name}\nElement Text: {element_text}\n\nThird-Party Tags Fired:\n" + "\n".join(
        [f"{tag[0]} - Load Time: {tag[1]}ms" for tag in tags])
    msg.attach(MIMEText(body, 'plain'))

    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(from_email, from_password)
    text = msg.as_string()
    server.sendmail(from_email, to_email, text)
    server.quit()


def close_overlay(driver):
    try:
        close_button = driver.find_element(By.CSS_SELECTOR, '.mc-modal-bg')
        close_button.click()
        time.sleep(1)
    except:
        pass


def click_element(driver, selector):
    close_overlay(driver)
    element = driver.find_element(By.CSS_SELECTOR, selector)
    element_text = element.text  # Capture the text of the clicked element
    driver.execute_script("arguments[0].scrollIntoView(true);", element)
    time.sleep(1)
    driver.execute_script("arguments[0].click();", element)
    return element_text


def run_check(url, selector, email, consent_selector=None, check_pii=False):
    driver = setup_driver()
    driver.get(url)

    st.write("Page loading...")

    time.sleep(5)  # Allow time for the page to load

    try:
        # Optional: Click the consent button if provided
        if consent_selector:
            st.write("Clicking consent button...")
            click_element(driver, consent_selector)
            time.sleep(2)  # Wait for any consent-driven scripts to load

        element_text = click_element(driver, selector)
        st.write("Element clicked, waiting for tags to fire...")

        time.sleep(5)  # Wait for tags to fire

        logs = get_network_logs(driver)
        tags, unique_pii = extract_tags_from_logs(logs, check_pii)

        if tags:
            send_email(email, selector, element_text, tags)
            st.success(f"Tags fired and emailed to {email}")

            # Display the tags in the app
            tag_df = pd.DataFrame(tags, columns=["Tag", "Load Time (ms)"])
            st.dataframe(tag_df)

            # Generate visual charts
            if len(tag_df) > 0:
                st.write("Tag Load Time Chart:")
                fig, ax = plt.subplots()
                tag_df.plot(kind='bar', x='Tag', y='Load Time (ms)', legend=False, ax=ax)
                ax.set_ylabel("Load Time (ms)")
                st.pyplot(fig)

            # Provide download option for the CSV
            csv = convert_df_to_csv(tag_df)
            st.download_button("Download CSV", csv, "tags_report.csv", "text/csv")

        else:
            st.warning("No third-party tags detected in the network logs.")

        if check_pii and unique_pii:
            st.warning(f"Unique PII found: {', '.join(unique_pii)}")

    except Exception as e:
        st.error(f"Error occurred: {str(e)}")
    finally:
        driver.quit()


def convert_df_to_csv(df):
    csv_buffer = StringIO()
    df.to_csv(csv_buffer, index=False)
    return csv_buffer.getvalue()


def main():
    st.title("Third-Party Tag Checker with Privacy Compliance")

    with st.expander("Basic Settings"):
        url = st.text_input("Enter the URL")
        selector = st.text_input("Enter the CSS Selector for the element to click")
        email = st.text_input("Enter your Email ID")
        interval = st.selectbox("Schedule Interval", ["None", "Daily", "Weekly"])

    with st.expander("Advanced Settings (Optional)"):
        consent_selector = st.text_input("Consent Button CSS Selector (Optional)", help="Specify a CSS selector to click for user consent.")
        check_pii = st.checkbox("Check for Potential PII in network logs")

    with st.expander("Run Checks"):
        if st.button("Run Check Now"):
            run_check(url, selector, email, consent_selector, check_pii)

        if st.button("Schedule Job"):
            if interval != "None":
                st.write(f"Scheduling {interval.lower()} job...")
                job_thread = threading.Thread(target=schedule_job, args=(interval, url, selector, email, consent_selector, check_pii))
                job_thread.start()


if __name__ == "__main__":
    main()