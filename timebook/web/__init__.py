import datetime
import logging
import os.path
import re
import sqlite3
import subprocess
import time
from functools import wraps

from flask import Flask, render_template

app = Flask(__name__)

HOME_DIR = "/home/";

class TimesheetRow(object):
    TICKET_MATCHER = re.compile(r"^(\d{4,6})(?:[^0-9]|$)+")
    TICKET_URL = "http://chili.parthenonsoftware.com/issues/%s/"

    @staticmethod
    def from_row(row):
        t = TimesheetRow()
        t.id = row[0]
        t.start_time_epoch = row[1]
        t.end_time_epoch = row[2]
        t.description = row[3]
        t.hours = row[4]
        return t

    @property
    def is_active(self):
        if not self.end_time_epoch:
            return True
        return False

    @property
    def start_time(self):
        return datetime.datetime.fromtimestamp(float(self.start_time_epoch))

    @property
    def end_time(self):
        if self.end_time_epoch:
            return datetime.datetime.fromtimestamp(float(self.end_time_epoch))

    @property
    def is_ticket(self):
        if self.description and self.TICKET_MATCHER.match(self.description):
            return True

    @property
    def ticket_url(self):
        if self.is_ticket:
            return self.TICKET_URL % self.TICKET_MATCHER.match(self.description).groups()[0]

    @property
    def end_time_epoch_or_now(self):
        if self.end_time_epoch:
            return self.end_time_epoch
        else:
            return time.time()

    @property
    def total_hours(self):
        return float(self.end_time_epoch_or_now - self.start_time_epoch) / 3600

def timesheet_row_factory(cursor, row):
    return TimesheetRow.from_row(row)

def dict_factory(cursor, row):
    d = {}
    for idx,col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def get_human_username(guess):
    """
    Will check with the passwd database to see if a full name is available
    for the current user.  If one is, it will return that, otherwise, it will
    return the current username.
    """
    process = subprocess.Popen(["getent", "passwd", guess], stdout = subprocess.PIPE)
    process_data = process.communicate()
    user_info_string = process_data[0]
    if user_info_string:
        user_info = user_info_string.split(":")
        user_details = user_info[4].split(",")
        if(user_details[0]):
            return user_details[0]
    return guess

def get_best_user_guess():
    """
    Searches for the most recently modified timebook database to find the
    most reasonable user.
    """
    dirs = os.listdir(HOME_DIR)
    max_atime = 0;
    final_user = None;
    for homedir in dirs:
        timebook_db_file = os.path.join(
                        HOME_DIR,
                        homedir,
                        ".config/timebook/sheets.db"
                    )
        if os.path.exists(timebook_db_file):
            if os.stat(timebook_db_file).st_atime > max_atime:
                final_user = homedir
    return final_user

def get_user_path(guess):
    """
    Using a supplied username, get the homedir path.
    """
    return os.path.join(HOME_DIR, guess)

def gather_information(view_func, *args, **kwargs):
    """Returns a valid database session for performing queries."""
    @wraps(view_func)
    def _wrapped_view_func(*args, **kwargs):
        user = get_best_user_guess()
        path_base = get_user_path(user)
        human_username = get_human_username(user)
        connection = sqlite3.Connection(
                os.path.join(
                    path_base, ".config/timebook/sheets.db"
                    )
                )
        connection.row_factory = timesheet_row_factory
        cursor = connection.cursor()
        return view_func(cursor, human_username, *args, **kwargs)
    return _wrapped_view_func

@app.route("/balance/")
@gather_information
def balance(cursor, human_username):
    return ""

@app.route("/")
@gather_information
def index(cursor, human_username):
    current = cursor.execute("""
        SELECT 
            id,
            start_time,
            end_time, 
            description, 
            ROUND((COALESCE(end_time, strftime('%s', 'now')) - start_time) / CAST(3600 AS FLOAT), 2) AS hours
        FROM entry 
        WHERE start_time = (select max(start_time) from entry);
        """).fetchone()
    todays_tasks = cursor.execute("""
        SELECT
            id, 
            start_time,
            end_time,
            description, 
            ROUND((COALESCE(end_time, strftime('%s', 'now')) - start_time) / CAST(3600 AS FLOAT), 2) AS hours
        FROM entry
        WHERE start_time > strftime('%s', strftime('%Y-%m-%d', 'now', 'localtime'), 'utc')
        ORDER BY start_time DESC
        """).fetchall()

    hours_total = 0
    for task in todays_tasks:
        hours_total = hours_total + task.total_hours

    return render_template("snapshot.html", 
            current = current,
            human_username = human_username,
            todays_tasks = todays_tasks,
            hours_total = hours_total
        )

from logging.handlers import SMTPHandler
mail_handler = SMTPHandler(
            "127.0.0.1",
            "timebook@localhost",
            "user@localhost",
            "Timebook encountered a problem",
        )
mail_handler.setLevel(logging.ERROR)
app.logger.addHandler(mail_handler)