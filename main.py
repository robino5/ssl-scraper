
import csv
import time
from datetime import datetime, time as datetime_time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from captcha_solver import solve_captcha


# ============================================================
# CONFIG
# ============================================================

USERNAME = "ibrokerlive@ssl"
PASSWORD = "Plclanka@26"

SQL_SERVER = "192.168.100.20"
SQL_DATABASE = "AnalyticDB"
MINTDB_DATABASE = "MINTDB"
SQL_USERNAME = "sa"
SQL_PASSWORD = "leads@123"
SQL_TABLE = "BI_trd_Admin_Fin_DayWise_SSL_details"

LOGIN_URL = "https://merchant.sslcommerz.com/"
LOGIN_ATTEMPTS = 5
DASHBOARD_LINK_SELECTOR = "a[href*='request=dTFyQWlkYXNoYm9hcmQ6dmlld3UxckFp']"

REPORT_INTERVAL_SECONDS = 10 * 60
BANGLADESH_TIMEZONE = timezone(timedelta(hours=6))
DAILY_STOP_TIME = datetime_time(14, 0)


def seconds_until_daily_stop():

    now = datetime.now(BANGLADESH_TIMEZONE)
    stop_at = now.replace(
        hour=DAILY_STOP_TIME.hour,
        minute=DAILY_STOP_TIME.minute,
        second=0,
        microsecond=0,
    )

    return max(0, (stop_at - now).total_seconds())


def build_report_url(report_date):

    report_date_text = report_date.strftime("%d-%m-%Y")

    return (
        "https://merchant.sslcommerz.com/"
        "?request=dTFyQWl0cmFuc2FjdGlvbnNNZXJjaGFudDpleGVjdXRl"
        "dTFyQWk%3D"
        "&generate=excel"
        f"&startDateTime={report_date_text}"
        f"&EndDateTime={report_date_text}"
        "&MerchantTransId="
        "&bankGw="
        "&storeName="
        "&cardNo="
        "&bankID="
        "&customerName="
        "&cardType="
        "&tStatus=dTFyQWlzdWNjZXNzdTFyQWk%3D"
        "&ip_address="
        "&isserlocation="
        "&transactionType="
        "&cus_phone="
        "&value_a="
        "&emistatus="
        "&brac_ref_id="
    )


# ============================================================
# DOWNLOAD DIRECTORY
# ============================================================

DOWNLOAD_DIR = (
    Path.cwd() / "downloads"
)

DOWNLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True
)

PAYMENT_CHANNELS = {
    "bkash": "BKash",
    "nagad": "Nagad",
    "bangla qr": "BANGLA QR",
    "pathao pay": "Pathao Pay",
}
SCB_CHANNEL = "SCB(NPSB)"
SUMMARY_CHANNELS = (*PAYMENT_CHANNELS.values(), "Card", SCB_CHANNEL)
EXTERNAL_PORTAL_BANKS = {"scb(npsb)"}


# ============================================================
# CHROME
# ============================================================

options = Options()

# IMPORTANT:
# Run WITHOUT headless first.
# This lets us see what SSLCOMMERZ is doing.
#
# options.add_argument("--headless=new")

options.add_argument("--start-minimized")

options.add_experimental_option(
    "prefs",
    {
        "download.default_directory": str(
            DOWNLOAD_DIR.resolve()
        ),

        "download.prompt_for_download": False,

        "download.directory_upgrade": True,

        "safebrowsing.enabled": True,

        "profile.default_content_setting_values.automatic_downloads": 1,
    }
)


driver = webdriver.Chrome(
    options=options
)

wait = WebDriverWait(
    driver,
    30
)


# ============================================================
# SHOW DOWNLOADS
# ============================================================

def show_downloads():

    files = list(
        DOWNLOAD_DIR.iterdir()
    )

    if not files:

        print(
            "No files downloaded."
        )

        return

    print()
    print(
        "Downloaded files:"
    )

    for file in files:

        print(
            " -",
            file.name
        )


def summarize_report(report_path, report_date):

    totals = {
        channel: {
            "count": 0,
            "amount": Decimal("0"),
        }
        for channel in SUMMARY_CHANNELS
    }

    required_columns = {
        "Date Time",
        "Bank",
        "Receivable",
        "Status",
    }

    with report_path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as report_file:
        reader = csv.DictReader(report_file)
        missing_columns = required_columns - set(reader.fieldnames or [])

        if missing_columns:
            raise RuntimeError(
                "The downloaded CSV is missing required columns: "
                + ", ".join(sorted(missing_columns))
            )

        for row in reader:
            if (row.get("Status") or "").strip().casefold() != "success":
                continue

            try:
                transaction_date = datetime.fromisoformat(
                    row["Date Time"].strip()
                ).date()
                receivable = Decimal(
                    row["Receivable"].replace(",", "").strip()
                )
            except (ValueError, InvalidOperation) as error:
                raise RuntimeError(
                    "Could not parse a successful transaction's date or "
                    "Receivable amount from the CSV."
                ) from error

            if transaction_date != report_date:
                raise RuntimeError(
                    f"The CSV contains transaction date {transaction_date}, "
                    f"but the requested report date is {report_date}. "
                    "No database rows were updated."
                )

            bank_name = " ".join((row.get("Bank") or "").split()).casefold()

            if bank_name.replace(" ", "") in EXTERNAL_PORTAL_BANKS:
                continue

            channel = PAYMENT_CHANNELS.get(bank_name, "Card")
            totals[channel]["count"] += 1
            totals[channel]["amount"] += receivable

    return [
        (
            channel,
            values["count"],
            values["amount"],
            datetime.combine(report_date, datetime.min.time()),
        )
        for channel, values in totals.items()
    ]


def quote_odbc_value(value):

    return "{" + value.replace("}", "}}") + "}"


def sql_connection_string(database):

    return (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={database};"
        f"UID={quote_odbc_value(SQL_USERNAME)};"
        f"PWD={quote_odbc_value(SQL_PASSWORD)};"
        "Encrypt=yes;TrustServerCertificate=yes;"
    )


def get_scb_npsb_summary():

    import pyodbc

    query = """
        SELECT COUNT(*), SUM(amount)
        FROM trd_Collection
        WHERE remarks = ?
    """

    with pyodbc.connect(
        sql_connection_string(MINTDB_DATABASE)
    ) as connection:
        result = connection.cursor().execute(
            query,
            "SCB NPS Collection",
        ).fetchone()

    return int(result[0]), Decimal(str(result[1] or 0))


def update_database(summary_rows):

    import pyodbc

    update_query = f"""
        UPDATE [{SQL_TABLE}]
        SET [No of transactions] = ?,
            [Amount] = ?,
            [Trade_dt] = ?
        WHERE [channel] = ?
    """

    with pyodbc.connect(
        sql_connection_string(SQL_DATABASE)
    ) as connection:
        cursor = connection.cursor()
        unmatched_channels = []

        for channel, transaction_count, amount, trade_date in summary_rows:
            cursor.execute(
                update_query,
                transaction_count,
                amount,
                trade_date,
                channel,
            )

            if cursor.rowcount != 1:
                unmatched_channels.append((channel, cursor.rowcount))

        if unmatched_channels:
            connection.rollback()
            details = ", ".join(
                f"{channel} ({count} rows matched)"
                for channel, count in unmatched_channels
            )
            raise RuntimeError(
                "Database update rolled back: each channel must match "
                f"exactly one existing row. Check: {details}. No rows were inserted."
            )

        connection.commit()

    print(
        f"Updated {len(summary_rows)} channel rows for "
        f"{summary_rows[0][3].date()}."
    )


class PortalSessionExpired(RuntimeError):
    pass


def fill_captcha():

    captcha_image = wait.until(
        EC.visibility_of_element_located(
            (By.CSS_SELECTOR, "img[src*='setCapture']")
        )
    )

    # Screenshot the rendered image instead of re-downloading it: every
    # request to setCapture generates a new code for this session.
    captcha_code = solve_captcha(captcha_image.screenshot_as_png)

    if captcha_code is None:
        return False

    print(f"CAPTCHA read as {captcha_code}.")
    captcha_field = driver.find_element(By.ID, "capture")
    captcha_field.clear()
    captcha_field.send_keys(captcha_code)

    return True


def login_portal():

    for attempt in range(1, LOGIN_ATTEMPTS + 1):
        print(f"Opening merchant portal (login attempt {attempt}/{LOGIN_ATTEMPTS})...")
        driver.get(LOGIN_URL)

        username = wait.until(
            EC.presence_of_element_located((By.ID, "user"))
        )
        username.clear()
        username.send_keys(USERNAME)

        password = driver.find_element(By.ID, "passwd")
        password.clear()
        password.send_keys(PASSWORD)

        if not fill_captcha():
            print("Could not read the CAPTCHA; loading a new one.")
            continue

        login_button = driver.find_element(By.ID, "wp-submit")
        print("Submitting login form...")
        login_button.click()

        try:
            wait.until(EC.staleness_of(login_button))
            wait.until(
                EC.any_of(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, DASHBOARD_LINK_SELECTOR)
                    ),
                    EC.presence_of_element_located((By.ID, "capture")),
                )
            )
        except TimeoutException:
            print("Login response timed out; retrying.")
            continue

        if driver.find_elements(By.CSS_SELECTOR, DASHBOARD_LINK_SELECTOR):
            print("Logged in.")
            print("Current URL:", driver.current_url)
            return

        print("Login rejected (likely a wrong CAPTCHA); retrying.")

    raise RuntimeError(
        f"Login failed after {LOGIN_ATTEMPTS} attempts. Check the "
        "username/password, or switch TROCR_MODEL in captcha_solver.py "
        "to microsoft/trocr-base-printed."
    )


def process_report_cycle():

    report_date = datetime.now(BANGLADESH_TIMEZONE).date()
    report_url = build_report_url(report_date)
    existing_files = {
        file.resolve()
        for file in DOWNLOAD_DIR.iterdir()
        if file.is_file()
    }

    print()
    print(f"Starting report update for {report_date}...")
    driver.get(report_url)

    page_text = driver.find_element(
        By.TAG_NAME,
        "body"
    ).text.lower()

    if "you have no permission" in page_text:
        raise RuntimeError(
            "SSLCOMMERZ denied the transaction report request. Verify the "
            "report URL/action and that this account has report/export access."
        )

    if "redirect=" in driver.current_url or any(
        field.is_displayed()
        for field in driver.find_elements(
            By.CSS_SELECTOR,
            "input[type='password']"
        )
    ):
        raise PortalSessionExpired(
            "The report request was redirected to the login page."
        )

    downloaded_report = None

    for attempt in range(60):
        files = [
            file
            for file in DOWNLOAD_DIR.iterdir()
            if file.is_file()
            and file.resolve() not in existing_files
            and file.suffix.lower() == ".csv"
        ]

        if files and not any(DOWNLOAD_DIR.glob("*.crdownload")):
            downloaded_report = max(
                files,
                key=lambda file: file.stat().st_mtime
            )
            print("CSV download detected:", downloaded_report)
            break

        print(f"Waiting for CSV download... {attempt + 1}/60")
        time.sleep(1)

    if downloaded_report is None:
        with open(
            "debug_page.html",
            "w",
            encoding="utf-8"
        ) as file:
            file.write(driver.page_source)

        raise RuntimeError(
            "No CSV transaction report was downloaded; database was not updated. "
            f"Current URL: {driver.current_url}; page title: {driver.title}. "
            "Saved debug_page.html."
        )

    summary_rows = summarize_report(downloaded_report, report_date)
    scb_count, scb_amount = get_scb_npsb_summary()
    summary_rows = [
        (channel, scb_count, scb_amount, trade_date)
        if channel == SCB_CHANNEL
        else (channel, transaction_count, amount, trade_date)
        for channel, transaction_count, amount, trade_date in summary_rows
    ]

    if seconds_until_daily_stop() <= 0:
        raise RuntimeError(
            f"{DAILY_STOP_TIME:%I:%M %p} Bangladesh time reached before the database update; "
            "the report was kept and no late update was started."
        )

    for channel, transaction_count, amount, trade_date in summary_rows:
        print(
            f"{channel}: {transaction_count} transactions, "
            f"amount {amount}, date {trade_date:%Y-%m-%d}"
        )

    update_database(summary_rows)
    downloaded_report.unlink()
    print("Deleted downloaded report:", downloaded_report.name)


# ============================================================
# MAIN
# ============================================================

try:

    # --------------------------------------------------------
    # LOGIN
    # --------------------------------------------------------
    login_portal()

    # --------------------------------------------------------
    # ENABLE DOWNLOAD THROUGH CHROME DEVTOOLS
    # --------------------------------------------------------

    driver.execute_cdp_cmd(
        "Browser.setDownloadBehavior",
        {
            "behavior": "allow",
            "downloadPath": str(
                DOWNLOAD_DIR.resolve()
            ),
        }
    )


    print(
        f"Automatic report updates every 10 minutes until {DAILY_STOP_TIME:%I:%M %p} "
        "Bangladesh time. Press Ctrl+C to stop."
    )

    while seconds_until_daily_stop() > 0:
        cycle_started = time.monotonic()

        try:
            process_report_cycle()
        except PortalSessionExpired as error:
            print(f"{error} Re-authenticating and retrying this report once.")

            try:
                login_portal()
                process_report_cycle()
            except Exception as retry_error:
                print(
                    "Report update failed after session recovery:",
                    retry_error
                )
        except Exception as error:
            print(f"Report update failed: {error}")

        wait_seconds = max(
            0,
            REPORT_INTERVAL_SECONDS - (time.monotonic() - cycle_started),
        )
        remaining_seconds = seconds_until_daily_stop()
        if remaining_seconds <= 0:
            break

        wait_seconds = min(wait_seconds, remaining_seconds)
        print(f"Next report update in {wait_seconds / 60:.1f} minutes.")
        time.sleep(wait_seconds)

    print(f"{DAILY_STOP_TIME:%I:%M %p} Bangladesh time reached. Closing browser.")


finally:

    driver.quit()
